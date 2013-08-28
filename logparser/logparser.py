#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import copy
import datetime
from gzip import GzipFile
import hashlib
import json
import logging
import optparse
import os
import shutil
import sys
import urllib

from mozautolog import ESAutologTestGroup as AutologTestGroup
from mozautolog import AutologBuildLog
from buildlog import BuildLogParser
from testsuiteparser import *
from tinderboxparser import *


DEFAULT_ES_SERVERS = ['localhost:9200']


class LogParser(object):

  # dictionary of parsers
  parsers = {
    'build': BuildLogParser,
    'mochitest': MochitestParser,
    'reftest': ReftestParser,
    'jsreftest': ReftestParser,
    'crashtest': ReftestParser,
    'xpcshell': XPCshellParser,
    }

  def __init__(self, uris, es=False, es_servers=None,
               includePass=False, harnessType='tinderbox',
               output_dir=None, delete_file=False, logger=None):
    self.uris = uris
    self.es = es
    self.includePass = includePass
    self.harnessType = harnessType
    self.output_dir = output_dir
    self.delete_file = delete_file
    self.logger = logger
    self.es_servers = es_servers or DEFAULT_ES_SERVERS[:]

    if self.output_dir:
      if not os.path.exists(self.output_dir):
        os.makedirs(self.output_dir)

  def _parseSingleFile(self, logname):

    # get the log
    try:
      log, headers = urllib.urlretrieve(logname)
    except IOError:
      log = logname

    try:
      fp = GzipFile(log)
      fp.readline()
      fp.seek(0)
    except IOError:
      fp = open(log, "rb")

    # parse the log
    parser = self.parsers.get(self.harnessType, TinderboxParser)(includePass=self.includePass)
    lineno, results = parser.parse(fp)
    fp.close()

    # dump output
    results.update({'filename': os.path.basename(logname)})

    # create a sha1 hash to be this json's id
    m = hashlib.sha1()
    m.update(json.dumps(results))
    id = ""
    if 'starttime' in results:
      id += str(results['starttime']) + '-'
    id += m.hexdigest()
    results.update({'id': id})

    return results

  def parseFiles(self):

    for logname in self.uris:

      if self.logger:
        self.logger.info('parsing file %s' % logname)

      try:
        testdata = self._parseSingleFile(logname)
      except Exception, inst:
        if self.logger:
          self.logger.exception('error parsing file %s' % logname)
        raise inst

      if self.es:
        self.postResultsToElasticSearch(testdata)

      # XXX this code assumes uris are local files; should verify
      if self.output_dir:
        to = os.path.join(self.output_dir, os.path.basename(logname))
        shutil.move(logname, to)

      if self.delete_file:
        os.remove(logname)

      return testdata

  def _post_testgroup_to_elasticsearch(self, data, index="logs"):
    testgroups = [AutologTestGroup(server=server,
                                   index=[index, index],
                                   doc_types=['builds', 'testruns',
                                              'testfailures'],
                                   machine=data['machine'],
                                   id=data['id'],
                                   starttime=data['starttime'],
                                   platform=data['platform'],
                                   os=data['os'],
                                   builder=data['builder'],
                                   harness='buildbot',
                                   testgroup=data['testgroup'],
                                   logurl=data['logurl'],
                                   errors=data.get('frameworkfailures', None),
                                   talosconfig=data.get('talosconfig', None))
                  for server in self.es_servers]

    for testgroup in testgroups:
      testgroup.set_primary_product(tree=data['tree'],
                                    revision=data['revision'],
                                    buildtype=data['buildtype'],
                                    buildid=data['buildid'],
                                    buildurl=data['buildurl'],
                                    )

      if 'testsuites' in data:
        for ts_index, ts in enumerate(data.get('testsuites', [])):
          testgroup.add_test_suite(testsuite=ts.get('suitename', None),
                                   elapsedtime=ts.get('elapsedtime', None),
                                   cmdline=ts.get('cmdline', None),
                                   passed=ts.get('passed', 0),
                                   failed=ts.get('failed', 0),
                                   todo=ts.get('todo', 0),
                                   id="%s-testsuite%d" % (data['id'], (ts_index+1)),
                                   )

          for tf_index, tf in enumerate(ts.get('failures', [])):
            for f in tf.get('failures', []):
              testgroup.add_test_failure(test=tf.get('test', None),
                                         id="%s-testfailure%d.%d" % (data['id'], (ts_index+1), (tf_index+1)),
                                         duration=tf.get('duration', None),
                                         **f
                                         )

          for tp_index, tp in enumerate(ts.get('passes', [])):
            testgroup.add_test_pass(doc_type='testpasses_' + testgroup.testsuites[-1].testsuite,
                                    test=tp.get('test'),
                                    id="%s-testpass%d.%d" % (data['id'], (ts_index+1), (tp_index+1)),
                                    duration=tp.get('duration'))

      if 'talossuites' in data:
        for ts_index, ts in enumerate(data.get('talossuites', [])):
          testgroup.add_talos_suite(testsuite=ts.get('suitename', None),
                                    elapsedtime=ts.get('elapsedtime', None),
                                    id="%s-talossuite%s" % (data['id'], (ts_index+1)),
                                    failure=ts.get('failure', None),
                                    report_format=ts.get('format', None),
                                    )

          for tr_index, tr in enumerate(ts.get('talosruns', [])):
            testgroup.add_talos_run(title=tr.get('test', None),
                                    result=tr.get('result', None),
                                    )

      testgroup.submit()

  def _post_buildlog_to_elasticsearch(self, data):
    postdata = copy.deepcopy(data)
    if 'filename' in postdata:
      del postdata['filename']
    for server in self.es_servers:
      AutologBuildLog(index='logs', server=server, **postdata).submit()

  def postResultsToElasticSearch(self, data):
    if 'talosconfig' in data:
      self._post_testgroup_to_elasticsearch(data, index = 'talos')
    elif 'testgroup' in data:
      self._post_testgroup_to_elasticsearch(data)
    elif 'buildname' in data:
      self._post_buildlog_to_elasticsearch(data)


def cli(args=sys.argv[1:]):

  parser = optparse.OptionParser(usage='%prog [options] file-or-url <file-or-url> ...')
  parser.add_option('-l', '--log', dest='log_file',
                    help="path to log file")
  parser.add_option("--include-pass",
                    action = "store_true", dest = "includePass",
                    default = False,
                    help = "include passing tests in the results")
  parser.add_option("--type",
                    action = "store", type = "string", dest = "harnessType",
                    default = "tinderbox",
                    help = "type of log file [default: tinderbox]")
  parser.add_option("--es",
                    action = "store_true", dest = "es",
                    help = "store data in ElasticSearch [default: false]")
  parser.add_option('-o', '--output-dir', dest='output_dir',
                    help="move logs to this directory after processing")
  parser.add_option('-d', '--delete', dest='delete_file',
                    action="store_true", default=False,
                    help="delete logs after processing")
  options, uris = parser.parse_args()

  if not args:
    parser.print_usage()
    parser.exit()

  # set up the logger if specified
  logger = None
  if options.log_file:
    logger = logging.getLogger('logparser')
    log_options = { 'format': "%(levelname)s | %(message)s",
                    'level': logging.INFO,
                    'filename': options.log_file }
    logging.basicConfig(**log_options)
    logger.info('logparser invoked at %s' % datetime.datetime.now().ctime())

  # generate a list of files to parse
  files = []
  for uri in uris:
    try:
      if os.path.isdir(uri):
        uri = os.path.abspath(uri)
        for f in os.listdir(uri):
          if os.path.isfile(os.path.join(uri, f)):
            files.append(os.path.join(uri, f))
        continue
    except:
      pass
    if os.path.exists(uri) or 'http://' in uri:
      files.append(uri)

  # parse the files
  lp = LogParser(files,
                 es=options.es,
                 includePass=options.includePass,
                 harnessType=options.harnessType,
                 output_dir=options.output_dir,
                 delete_file=options.delete_file,
                 logger=logger,
                )
  print json.dumps(lp.parseFiles(), indent=2)

  if logger:
    logger.info('logparser shutting down at %s' % datetime.datetime.now().ctime())

if __name__ == '__main__':
  cli()
