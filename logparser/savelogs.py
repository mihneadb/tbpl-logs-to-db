# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import gzip
import json
import logging
import logging.handlers
from multiprocessing import Process, Queue
import os
from Queue import Empty
import signal
import socket
import sys
import time
import urllib2

from config import platform_list, test_list, trees_to_watch
from io import BytesIO
from logparser import LogParser
from optparse import OptionParser
from pulsebuildmonitor import PulseBuildMonitor


class BuildLogParser(object):

  def __init__(self, queue, parent_pid=None, logger=None, es=False,
               es_servers=None, output_dir=None, include_pass=None):
    self.logger = logger
    self.include_pass = include_pass
    self.es = es
    self.es_servers = es_servers
    self.output_dir = output_dir
    self.job_queue = queue
    self.parent_pid = parent_pid

  def parse(self):
    while True:
      try:
        os.kill(self.parent_pid, 0)
        logfile, harnessType = self.job_queue.get_nowait()
      except Empty:
        time.sleep(5)
        continue
      except OSError:
        sys.exit(0)

      self.logger.info('parsing %s' % logfile)
      if logfile == 'exit':
        break
      try:
        lp = LogParser([logfile],
                       es=self.es,
                       es_servers=self.es_servers,
                       includePass=self.include_pass,
                       output_dir=self.output_dir,
                       logger=self.logger,
                       harnessType=harnessType,
                      )
        lp.parseFiles()
      except Exception, inst:
        self.logger.exception(inst)


class BuildLogMonitor(PulseBuildMonitor):

  def __init__(self, logdir='logs', outputlog='buildlogmonitor.out',
               errorlog='buildlogmonitor.err', es=False, es_servers=None,
               output_dir=None, include_pass=None, **kwargs):
    self.logdir = os.path.abspath(logdir)
    self.logger = None
    self.es = es
    self.es_servers = es_servers
    self.output_dir = output_dir
    self.include_pass = include_pass

    self.job_queue = Queue()

    # setup logging
    if outputlog:
      self.logger = logging.getLogger('BuildLogMonitor')
      self.logger.setLevel(logging.DEBUG)
      loghandler = logging.handlers.RotatingFileHandler(
                   outputlog, maxBytes=1000000, backupCount=3)
      loghandler.setLevel(logging.DEBUG)
      formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
      loghandler.setFormatter(formatter)
      self.logger.addHandler(loghandler)

      if errorlog:
        errhandler = logging.FileHandler(errorlog, 'w')
        errhandler.setLevel(logging.ERROR)
        errhandler.setFormatter(formatter)
        self.logger.addHandler(errhandler)

    self.processes = [self._start_parser_process() for x in range(2)]

    PulseBuildMonitor.__init__(self, logger=self.logger, trees=trees_to_watch, **kwargs)

    signal.signal(signal.SIGTERM, self.sighandler)

  def sighandler(self, signumber, frame):
    # dump any pending items in the queue and then quit
    f = open(os.path.join(os.path.dirname(self.logdir), 'pending_jobs.txt'), 'w')
    filedata = []
    while True:
      try:
        logfile, harnessType = self.job_queue.get_nowait()
        filedata.append([logfile, harnessType])
      except Empty:
        break
      except Exception, inst:
        if self.logger:
          self.logger.exception(inst)
    f.write("%s\n" % json.dumps(filedata))
    f.close()
    os.kill(os.getpid(), signal.SIGKILL)

  def _start_parser_process(self):
    logparser = BuildLogParser(self.job_queue,
                               include_pass=self.include_pass,
                               es=self.es,
                               es_servers=self.es_servers,
                               output_dir=self.output_dir,
                               logger=self.logger,
                               parent_pid=os.getpid()
                              )
    logprocess = Process(target=logparser.parse)
    logprocess.start()
    return logprocess

  def _download_and_parse_log(self, logname, logurl, type='tinderbox', buildername='None'):
    # download the log file and extract it...
    remote = urllib2.urlopen(logurl)
    gzfile = gzip.GzipFile(fileobj=BytesIO(remote.read()))

    # ...insert the logurl at the beginning of the log...
    data = str('logurl: %s\nbuildername: %s\n%s' %
                                  (logurl,
                                   buildername,
                                   unicode(gzfile.read(), errors='ignore')))
    gzfile.close()
    outfile = os.path.join(self.logdir, logname)

    # ...and finally write the whole thing to disk
    size = len(data)
    localgz = gzip.open(outfile, 'wb')
    localgz.write(data)
    localgz.close()

    if self.logger:
      self.logger.info("%d bytes written to %s" % (size, outfile))

    # now parse the file in a separate thread
    self.job_queue.put((outfile, type))

  def on_build_complete(self, builddata):
    try:
      if self.logger:
        self.logger.info(">>>>>>>>>>>>>> Build Complete!")
        self.logger.info(json.dumps(builddata, indent=2))

      # generate the name of the saved log file
      logname = os.path.basename(builddata['logurl'])

      buildername = builddata.get('buildername', 'None')
      self._download_and_parse_log(logname,
                                   builddata['logurl'],
                                   type='build',
                                   buildername=buildername)

    except Exception, inst:
      if self.logger:
        self.logger.exception(inst)

  def on_test_complete(self, builddata):
    try:
      if self.logger:
        self.logger.info(">>>>>>>>>>>>>> Test Complete!")
        self.logger.info(json.dumps(builddata, indent=2))

      # generate the name of the saved log file
      logname = '%s-%s-%s-%s-%d-%s.txt.gz' % (builddata['tree'],
                                              builddata['os'],
                                              builddata['platform'],
                                              builddata['buildtype'],
                                              builddata['builddate'],
                                              builddata['test'])

      buildername = builddata.get('buildername', 'None')
      self._download_and_parse_log(logname,
                                   builddata['logurl'],
                                   buildername=buildername)

    except Exception, inst:
      if self.logger:
        self.logger.exception(inst)

  def start(self):
    # create the logdir if it doesn't exist
    if not os.access(self.logdir, os.F_OK):
      os.mkdir(self.logdir)

    while True:
      try:
        # now start listening for pulse messages; this call will never return
        self.listen()
      except KeyboardInterrupt:
        break
      except Exception, inst:
        if self.logger:
          self.logger.exception(inst)
        time.sleep(60)

def main():
  # parse options
  parser = OptionParser()
  parser.add_option('--errorlog', dest='errorlog', action='store',
                    help='path to file for logging errors')
  parser.add_option('--outputlog', dest='outputlog', action='store',
                    help='path to file for logging all activity')
  parser.add_option('--savedir', dest='logdir', action='store',
                    default='incoming',
                    help='path to directory for saving incoming logs')
  parser.add_option("--include-pass",
                    action = "store_true", dest = "include_pass",
                    default = False,
                    help = "include passing tests in the results")
  parser.add_option("--es",
                    action = "store_true", dest = "es",
                    help = "store data in ElasticSearch [default: false]")
  parser.add_option("--durable",
                    action = "store_true", dest = "durable",
                    help = "use a durable pulse consumer [default: false]")
  parser.add_option('--outputdir', dest='output_dir',
                    help="move logs to this directory after processing")
  parser.add_option('--es-server', dest='es_servers', action='append',
                    help='address of ElasticSearch server; can be specified '
                    'multiple times [default: localhost:9200]')
  parser.add_option('--include-talos', dest='include_talos', action='store_true',
                    help='flag to include talos tests')
  parser.add_option('--pidfile', dest='pidfile',
                    help='path to file for logging pid')
  options, args = parser.parse_args()

  if not options.es_servers:
    options.es_servers = ['localhost:9200']

  if options.pidfile is not None:
    fp = open(options.pidfile, "w")
    fp.write("%d\n" % os.getpid())
    fp.close()

  monitor = BuildLogMonitor(logdir=options.logdir,
                            outputlog=options.outputlog,
                            errorlog=options.errorlog,
                            es=options.es,
                            es_servers=options.es_servers,
                            output_dir=options.output_dir,
                            include_pass=options.include_pass,
                            label='woo@mozilla.com|logparser' + socket.gethostname(),
                            platforms=platform_list,
                            tests=test_list,
                            unittests=True,
                            builds=True,
                            durable=options.durable,
                            talos=options.include_talos,
                           )
  monitor.start()

if __name__ == "__main__":
  main()
