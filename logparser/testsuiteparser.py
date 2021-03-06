# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

__all__ = ['TestSuiteLogParser',
           'ReftestParser',
           'XPCshellParser',
           'MochitestParser',
          ]

import datetime
import re


class TestSuiteLogParser(object):
  """Base class for parsing test suite logs (e.g., mochitest, etc).
  """

  # tinderbox end-of-testrun delimiters on Win+Linux, Mac
  endTestrunDelimiters = ["======== Finished",
                          "=== Output ended ==="]
  # potential tinderbox errors
  testrunerrorstrings = ['remoteFailed:']
  testruntimeoutstrings = ['buildbot.slave.commands.TimeoutError: command timed out']
  extracrashstrings = ['has caught an Obj-C exception']

  # 'TestFailed' expected log format is "result | test | optional text".
  testfailedRe = re.compile(r".*?(TEST-UNEXPECTED-.*|PROCESS-CRASH) \| (.*)\|(.*)")
  # elapsed time for test run
  elapsedTimeRe = re.compile(r"elapsedTime=(\d+)")
  # beginning of stack trace for crashed thread
  stackRe = re.compile(r"^.*?Thread (\d+) \(crashed\)")
  # beginning of a stack trace frame
  stackTraceFrameRe = re.compile(r"^\s*(\d+)\s+(.+)")

  def __init__(self,
               cmdline=None,
               includePass=False,
               builddate=None,
               linenumber=0,
               tree=None):
    self.elapsedTime = 0
    self.passed = None
    self.failed = None
    self.todo = None
    self.lastError = None
    self.testfailures = []
    self.testpasses = []
    self.lastFailedTest = None
    self.suitename = None
    self.includePass = includePass
    self.lastPassedTest = None
    self.tree = tree
    self.builddate = builddate
    if cmdline:
      self.suitename = self.getTestSuiteName(cmdline)
    self.linepos = 0
    self.linenumber = linenumber

  def getStartTime(self, fp):
    line = fp.readline()
    while "starttime" not in line:
      line = fp.readline()

    self.starttime = float(line.split(": ")[1])
    fp.seek(0)

  def getSlaveType(self, fp):
    line = fp.readline().strip()
    line = line.split('mozilla-inbound_')[1]
    self.slavetype = line[:line.index('_test')]
    fp.seek(0)

  def normalizeTestName(self, test):
    """Normalize the test name"""

    # For some generic errors, set the test name to 'Shutdown', which causes
    # them to be promoted to testrun errors, instead of testcase errors.
    if test == 'Main app process exited normally' or \
       test == 'automationutils.processLeakLog()':
      return 'Shutdown'

    # Make test names consistent
    if test.find('\\') != -1:
      test = test.replace('\\','/')
    if test.find('/') != -1:
      ret=test.split('build/')
      if len(ret) > 1:
        test=ret[1]
      else:
        test=ret[0]

    return test

  def setLastFailedTest(self, test, text):
    """Update self.lastFailedTest as appropriate"""
    self.lastFailedTest = test

  def processLine(self, line):
    """Do any extra processing that's needed"""
    pass

  def normalizeTestNameAndReason(self, test, reason, text):
    """Normalize the test name and reason"""

    # assign TEST-LEAKED to leak errors
    if test == 'automationutils.processLeakLog()' and \
       text != 'missing output line for total leaks!':
      reason = 'TEST-LEAKED'

    # assign TEST-TIMEOUT to timeout errors
    if text and ('application timed out after' in text or 'Test timed out' in text or \
       'timed out waiting for' in text):
      reason = 'TEST-TIMEOUT'

    # for test errors that occur for 'automation.py' , change name
    # to 'Shutdown' so that they are promoted to testrun errors not
    # related to a specific test case
    if test == 'automation.py':
      test = 'Shutdown'

    # normalize the test name
    test = self.normalizeTestName(test)
    return (test, reason)

  def result(self):
    """Collect test run data into a dict and return it. The dict has the
       following structure:

       passed: the number of passed tests.  For mochitest, this is the
               number of passed assertions, not test files
       failed: the number of failed tests.
       todo: the number of todo tests or known failures.

       testfailures: a list of test errors that occurred during the test run.
                     Each item in the list is a dict with the following keys:
         test: the name of the test
         failures: a list of failures that occurred duing that test; each
                   item is a dict with the following keys:
           text: a description of the error
           reason: one of TEST-UNEXPECTED-FAIL, TEST-TIMEOUT, TEST-LEAKED,
                   TEST-UNEXPECTED-PASS, or PROCESS-CRASH
           stacktrace: if the reason is PROCESS-CRASH, this may contain
                       the stack trace of the crashed thread
           imageN: for reftest, failures may include one or more image keys,
                   containing base64-encoded strings of the failing screen
                   captures
       testpasses: a list of strings representing tests that passed.  This is
                   only generated if --include-pass was specified on the
                   command-line.

       The following keys only exist when this parser was called from the
       tinderbox log parser:

       suitename: e.g., 'mochitest-chrome'
       elapsedtime: the duration of the test run in seconds

    """

    result = {}

    result['starttime'] = self.starttime
    result['slavetype'] = self.slavetype

    result.update({ 'passes': self.testpasses })

    result.update({ 'failures': self.testfailures })

    result.update({ 'testfailure_count': len(self.testfailures) })
    if self.suitename:
      result.update({ 'suitename': self.suitename })
    if self.elapsedTime:
      result.update({ 'elapsedtime': self.elapsedTime })
    if self.passed is not None:
      result.update({ 'passed': self.passed })
    if self.failed is not None:
      result.update({ 'failed': self.failed })
    if self.todo is not None:
      result.update({ 'todo': self.todo })

    return result

  def add_test_failure(self, test, thisfailure):
    appended = False
    for failure in self.testfailures:
      if failure['test'] == test:
        failure['failures'].append(thisfailure)
        appended = True
        break
    if not appended:
      self.testfailures.append({'test': test,
                                'failures': [thisfailure] })

  def parse(self, fp):
    """Parse the logfile, until EOF or one of the endTestrunDelimiters
       is found.
    """

    processingCrash = False
    processingStackTrace = False
    stackTrace = ""

    self.getSlaveType(fp)
    self.getStartTime(fp)

    #for line in fp:
    while 1:
      self.linepos = fp.tell()
      line = fp.readline()
      self.linenumber += 1
      if not line:
        break

      line = line.rstrip()

      # test to see if the line is a failure
      m = self.testfailedRe.match(line)
      if m:
        processingCrash = False

        # reason for failure [TEST-UNEXPECTED-.* or PROCESS-CRASH]
        reason = m.group(1).rstrip()

        # name of the test
        test = m.group(2).strip().rstrip() or "Shutdown"

        # fail log text
        text = m.group(3).strip() or None

        test, reason = self.normalizeTestNameAndReason(test, reason, text)
        thisfailure = {'status': reason}
        if text:
          thisfailure.update({'text': text})

        # add the failure to the correct place in the self.testfailures list
        self.add_test_failure(test, thisfailure)

        # update the last failed test name
        self.setLastFailedTest(test, text)

        # if this failure was added to our list of passed tests, remove it
        if test == self.lastPassedTest:
          self.lastPassedTest = None
          self.testpasses = self.testpasses[0:-1]

        # a crash occurred, start looking for the stack trace
        if 'PROCESS-CRASH' in reason:
          processingCrash = True
          processingStackTrace = False
          stackTrace = ""

        continue

      # look for a stack trace if needed
      if processingCrash:
        m = self.stackRe.match(line)
        if m:
          processingStackTrace = True
        # we assume that a stack trace ends with a blank line
        if processingStackTrace:
          m = self.stackTraceFrameRe.match(line)
          if line.rstrip() == '' or (m and int(m.group(1)) > 5):
            processingStackTrace = False
            processingCrash = False
            self.testfailures[-1]['failures'][-1].update({'stacktrace': stackTrace})
            continue
        if processingStackTrace:
          # add the current line to the stack trace
          stackTrace += line + '\n'
          continue

      # perform extra processing as needed
      self.processLine(line)

      # For now, we'll only record passed tests on Tuesdays.  We don't need
      # day-by-day granularity, and this will save the db from getting too
      # bloated.
      if self.includePass:
      #if (self.includePass and self.suitename == 'mochitest' and
      #    self.tree == 'mozilla-central' and
      #    datetime.datetime.now().isoweekday() == 2):
        m = self.passTestRe.match(line)
        if m:
          startTestName = self.normalizeTestName(m.group(2))
          if startTestName != 'Shutdown':
            self.lastPassedTest = startTestName
            if len(self.testpasses) == 0 or self.lastPassedTest != self.testpasses[-1]['test']:
              self.testpasses.append({'test': self.lastPassedTest})

      # look for the 'test-finished' marker
      if self.checkForTestFinish(line):
        self.lastFailedTest = None
        continue

      # look for tinderbox elapsedTime
      if not self.elapsedTime:
        m = self.elapsedTimeRe.match(line)
        if m:
          self.elapsedTime = m.group(1)
          continue

      # look for passed/failed/todo numbers
      if self.passed is None:
        self.passed = self.getPassed(line)
        if self.passed:
          continue
      if self.failed is None:
        self.failed = self.getFailed(line)
        if self.failed:
          continue
      if self.todo is None:
        self.todo = self.getTodo(line)
        if self.todo:
          continue

      # look for tinderbox end-of-testrun delimiters, and return if found
      #for delimiter in self.endTestrunDelimiters:
        #if delimiter in line:
          #return (self.linenumber, self.result())

      # look for tb errors that might appear in the log
      for error in self.testrunerrorstrings:
        if error in line:
          self.add_test_failure('Shutdown',
                              {'status': 'TEST-UNEXPECTED-FAIL', 'text': line.rstrip()})
          continue
      for error in self.testruntimeoutstrings:
        if error in line:
          self.add_test_failure('Shutdown',
                              {'status': 'TEST-TIMEOUT', 'text': line.rstrip()})
          continue

      # look for more strings that indicate a crash
      for error in self.extracrashstrings:
        if error in line:
          self.add_test_failure('Shutdown',
                              {'status': 'PROCESS-CRASH', 'text': line.rstrip()})

    # we reached EOF, so return the result
    return (self.linenumber, self.result())

class MochitestParser(TestSuiteLogParser):
  """
  applies to
  - Mochitest-plain
  - Mochitest-chrome
  - Mochitest-browserchrome
  - Mochitest-a11y
  """

  # number of passed tests
  passedRe = re.compile(r".*?(INFO |\t)Passed:(\s+)(\d+)")
  # number of failed tests
  failedRe = re.compile(r".*?(INFO |\t)Failed:(\s+)(\d+)")
  # number of todo tests
  todoRe = re.compile(r".*?(INFO |\t)Todo:(\s+)(\d+)")

  # for mochitest, we assume that every TEST-START case passes, until
  # we see otherwise
  passTestRe = re.compile(r"^(.*?)TEST-START \| (.*)$")

  # end of test case
  endTestRe = re.compile(r"^.*?INFO .*?Test finished (.*?) in (\d+)ms")
  endTestRe2 = re.compile(r"^.*?TEST-END \| (.*?) \| finished in (\d+)ms")

  # command-line for mochitest-plain runs in tinderbox
  chunkRe = re.compile(r"^.*?--this-chunk=(\d)")

  unexpectedException = 'INFO | runtests.py | Received unexpected exception'

  def getTodo(self, line):
    m = self.todoRe.match(line)
    if m:
      return m.group(3)

  def getFailed(self, line):
    m = self.failedRe.match(line)
    if m:
      return m.group(3)

  def getPassed(self, line):
    m = self.passedRe.match(line)
    if m:
      return m.group(3)

  def getTestSuiteName(self, cmdline):
    """Returns the test suite name"""
    if '--chrome' in cmdline:
      return 'mochitest-chrome'
    if '--browser-chrome' in cmdline:
      return 'mochitest-browser-chrome'
    if '--a11y' in cmdline:
      return 'mochitest-a11y'
    if '--setpref=dom.ipc.plugins' in cmdline:
      return 'mochitest-ipcplugins'
    m = self.chunkRe.match(cmdline)
    if m:
      return 'mochitest-plain-' + str(m.group(1))
    return 'mochitest'

  def checkForTestFinish(self, line):
    """Returns True if this line contains the test duration at the end of a test.
    """
    duration = None
    m = self.endTestRe.match(line)
    if m:
      # if the test that just finished is the last
      # test in our failed list, update it's duration.
      duration = m.group(2)
      endtestname = self.normalizeTestName(m.group(1))
    m = self.endTestRe2.match(line)
    if m:
      duration = m.group(2)
      endtestname = self.normalizeTestName(m.group(1))

    if duration:
      # If a duration was found for this test, and this test is the
      # current failing or passing test, update the test object with
      # the duration.
      if self.testfailures and self.testfailures[-1]['test'] == endtestname:
        self.testfailures[-1].update({'duration': duration})
      if self.testpasses and self.testpasses[-1]['test'] == endtestname:
        self.testpasses[-1].update({'duration': duration})
      return True

    return False

  def processLine(self, line):
    if not line.startswith(self.unexpectedException):
      return

    self.add_test_failure('Shutdown',
      {'status': 'PROCESS-CRASH', 'text': line.rstrip()})


class XPCshellParser(TestSuiteLogParser):
  """
  parser XPCShell results
  """
  # number of passed tests
  passedRe = re.compile(r".*?INFO \| Passed:(\s+)(\d+).*")
  # number of failed tests
  failedRe = re.compile(r".*?INFO \| Failed:(\s+)(\d+)")

  # passed test case
  passTestRe = re.compile(r"^(.*?)TEST-PASS \| (.*) \| test passed( \(time: (\d+))?")

  def getTodo(self, line):
    return None

  def getPassed(self, line):
    m = self.passedRe.match(line)
    if m:
      return m.group(2)

  def getFailed(self, line):
    m = self.failedRe.match(line)
    if m:
      return m.group(2)

  def setLastFailedTest(self, test, text):
    """Update self.lastFailedTest as appropriate"""
    # xpcshell logging is a little different from the other harnesses,
    # in that failure details often include TEST-UNEXPECTED-FAIL with a
    # a test name of something that isn't the real test, e.g., (xpcshell/head.js).
    # However, the first TEST-UNEXPECTED-FAIL for a given test does have
    # the correct name.  Therefore, we keep track of the first test name
    # for a given failure, and all subsequent failures are assigned that
    # same test name, until we see '  <<<<<<<' in the log, which indicates
    # that output for a given failure is finished.
    if text and 'see following log:' in text:
      self.lastFailedTest = test

  def checkForTestFinish(self, line):
    """Returns True if this line marks the end of a test"""
    # for xpcshell tests, the string '  <<<<<<<' marks the end of a failed test
    if '  <<<<<<<' in line:
      return True

    duration = None
    # for passing tests, look for TEST-PASS
    m = self.passTestRe.match(line)
    if not m:
      return False

    duration = m.group(4)
    if duration:
      endtestname = self.normalizeTestName(m.group(2))
      if self.testpasses and self.testpasses[-1]['test'] == endtestname:
        self.testpasses[-1].update({'duration': duration})

    return True

  def normalizeTestName(self, test):
    """Normalize the test name"""
    # If we're inside a test failure already, reset the test name to the
    # existing failure's name.  This allows us to avoid having errors show
    # up for things like (xpcshell/head.js), which aren't real tests.
    if self.lastFailedTest is not None:
      test = self.lastFailedTest

    return TestSuiteLogParser.normalizeTestName(self, test)

  def getTestSuiteName(self, cmdline):
    """Returns the test suite name"""
    return 'xpcshell'


class ReftestParser(TestSuiteLogParser):
  """
  applies to
  - Reftest
  - Crashtest
  - JSReftest
  """

  # number of passed tests
  passedRe = re.compile(r".*?INFO \| Successful:(\s+)(\d+).*")
  # number of failed tests
  failedRe = re.compile(r".*?INFO \| Unexpected:(\s+)(\d+)")
  # number of todo tests
  todoRe = re.compile(r".*?INFO \| Known problems:(\s+)(\d+)")

  # passed test case
  passTestRe = re.compile(r"^(.*?)TEST-PASS \| (.*?) \|(.*)$")

  # image data
  imageRe = re.compile(r"^.*?IMAGE (\d+) \(.*?\): (.*)")

  # end of test line
  endTestRe = re.compile(r"^.*?REFTEST INFO \| Loading a blank page")

  def getTodo(self, line):
    m = self.todoRe.match(line)
    if m:
      return m.group(2)

  def getPassed(self, line):
    m = self.passedRe.match(line)
    if m:
      return m.group(2)

  def getFailed(self, line):
    m = self.failedRe.match(line)
    if m:
      return m.group(2)

  def processLine(self, line):
    """Do any extra processing that's needed"""

    # look for reftest images if appropriate
    if self.testfailures:
      m = self.imageRe.match(line)
      if m:
        image = "image" + str(m.group(1)) + "linenumber"
        data = m.group(2)
        self.testfailures[-1]['failures'][-1].update({image: self.linenumber})

  def checkForTestFinish(self, line):
    """Returns True if this line marks the end of a test."""
    m = self.endTestRe.match(line)
    if m:
      return True
    return False

  def getTestSuiteName(self, cmdline):
    """Returns the test suite name"""
    if 'jsreftest' in cmdline:
      return 'jsreftest'
    if 'crashtest' in cmdline:
      return 'crashtest'
    return 'reftest'
