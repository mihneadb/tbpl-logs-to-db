# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

__all__ = ['TalosLogParser',
          ]

import re

class TalosLogParser(object):
  """ Parser for extracting talos test runs from browser logs."""

  # RE for end of test section of log
  talosEndTestRe = re.compile(r"^Completed test (.*?):$")

  # RE for start and end of test report
  tpStartReportRe = re.compile(r"^.*__start_tp_report$")
  tpEndReportRe = re.compile(r"^.*__end_tp_report$")

  # RE for page load
  tpTestResultRe = re.compile(r"^.*\|(\d*?);([^;]*?);([^;]*?);([^;]*?);([^;]*?);([^;]*?);(.*?)$")

  # Re for ts stype reports
  tsTestResultRe = re.compile(r"^.*__start_report(.*?)__end_report.*$")

  # RE for start and end timestamps
  startTimestampRe = re.compile(r"^.*__startTimestamp(.*?)__endTimestamp.*$")
  endTimestampRe = re.compile(r"^.*__startAfterTerminationTimestamp(.*?)__endAfterTerminationTimestamp.*$")

  # RE for test failure
  failureRe = re.compile(r"^.*__FAIL(.*?)__FAIL$")

  def __init__(self,
               builddate=None,
               linenumber=0,
               tree=None,
               testname=None):
    self.startTime = 0
    self.endTime = 0
    self.suitename = testname
    self.tree = tree
    self.builddate = builddate
    self.linenumber = linenumber
    self.talosruns = []
    self.failure = None
    self.ts_runs = []
    self.report_type = None

  def result(self):
    """ Creates output dictionary from parsed data

        Dictionary includes:
        testsruns - list of dictionarys with "test" and "result" keys.
        failure - the failure string if failure present
        suitename - the name of the test being run
        elapsedtime - the time taken for the test
        format - defining the data format (ts_format, tp_format)
    """
    result = {}

    if self.ts_runs:
      self.talosruns.append({ 'test' : self.suitename,
                             'result' : ','.join(self.ts_runs) })

    result.update({ 'talosruns': self.talosruns,
                    'format': self.report_type})

    if self.failure:
      result.update({ 'failure': self.failure })

    if self.suitename:
      result.update({ 'suitename': self.suitename })

    if self.startTime and self.endTime:
      result.update({ 'elapsedtime': self.endTime - self.startTime })

    return result

  def parse(self, fp):
    """ Parses the file-like object for a talos run. until EOF or "Completed test ..."""

    processingTpReport = False

    while 1:
      line = fp.readline()
      self.linenumber += 1
      if not line:
        break

      line = line.rstrip()

      m = self.failureRe.match(line)
      if m:
        self.failure = m.group(1)
        break

      # in a tp_report so look for valid test lines
      if processingTpReport:
        m = self.tpEndReportRe.match(line)
        if m:
          processingTpReport = False
          continue
        m = self.tpTestResultRe.match(line)
        if m:
          test = m.group(2)
          results = m.group(7).replace(';',',')
          self.talosruns.append({'test':test,
                                'result':results})
        continue

      # look for start of tp report
      m = self.tpStartReportRe.match(line)
      if m:
        self.report_type = "tp_format"
        processingTpReport = True
        continue

      m = self.tsTestResultRe.match(line)
      if m:
        self.report_type = "ts_format"
        self.ts_runs.append(m.group(1).replace('|',','))

      # look for the start timestamp
      if not self.startTime:
        m = self.startTimestampRe.match(line)
        if m:
          self.startTime = int(m.group(1))

      # look for the end timestamp
      m = self.endTimestampRe.match(line)
      if m:
        self.endTime = int(m.group(1))

      # look for the end of the test
      m = self.talosEndTestRe.match(line)
      if m:
        break

    # we reached EOF, so return the result
    return (self.linenumber, self.result())


