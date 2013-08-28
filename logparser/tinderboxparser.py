#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

__all__ = ['TinderboxParser'
          ]

from config import trees_to_watch
import datetime
from mozautolog import ESAutologTestGroup as AutologTestGroup
import re
from testsuiteparser import *
from taloslogparser import *


class TinderboxParser(object):
  """Parser for parsing tinderbox logs"""

  # dictionary of parsers
  parsers = {
    'mochitest': MochitestParser,
    'reftest': ReftestParser,
    'jsreftest': ReftestParser,
    'crashtest': ReftestParser,
    'xpcshell': XPCshellParser,
    }

  #
  # some constants and regexp's used to examine each line of the log
  #

  # builder
  builderRe = re.compile(r"^builder: (.*)$")
  # logurl
  logUrlRe = re.compile(r"^logurl: (.*)$")
  # starttime
  starttimeRe = re.compile(r"^starttime: (.*?)\.")
  # hg revision
  revisionRe = re.compile(r"^revision: (.*)$")
  # machine that the test was executed on
  machineRe = re.compile(r"^(Building on|slave): (.*)$")
  # we find the build url by looking for wgets; we assume the first one
  # is for the build
  buildRe = re.compile(r"^\s*argv: \['wget', '--progress=dot:mega', '-N', u'(.*?)'\]$")
  # buildid
  buildIdRe = re.compile(r"^buildid: '(\d+)'$")

  # finds the command-line used to start a test run
  mochitestRe = re.compile(r"^(python mochitest|'python' 'mochitest).*")
  reftestRe = re.compile(r"^(python reftest|'python' 'reftest).*")
  xpcshellRe = re.compile(r"^.*?-u xpcshell/runxpcshelltests.py")

  # finds the configuration creation line for a talos run
  talosConfigRe = re.compile(r"^'?python'? '?(remote)?PerfConfigurator.py'?.*")

  # finds the notification of the start of a talos test
  talosTestRe = re.compile(r"^Running test (.*?):$")

  # list of possible platforms used in build url's
  platforms = ['win32', 'win64', 'macosx64', 'macosx', 'linux64', 'linux']
  # list of repos used in build url's
  trees = trees_to_watch
  # lines to look for that indicates tinderbox problems; usually these occur
  # in the context of, and are caught by, the test suite parsers, but
  # they could occur elsewhere in the log as well
  tberrs = ['remoteFailed:',
            'buildbot.slave.commands.TimeoutError: command timed out']

  testgroupRe = re.compile(r'(%s)[-|_](.*?)(-debug|-o-debug|_pgo|-pgo)?[-|_](test|unittest)(_pgo|-pgo)?-(.*)' % '|'.join(trees))


  def __init__(self, includePass=False):
    # by default, we ignore passing tests, but we can keep a list of them
    # if this parameter is set
    self.includePass = includePass

    # initialize some other variables
    self.builder = None
    self.logurl = None
    self.starttime = None
    self.revision = None
    self.machine = None
    self.build = None
    self.testruns = []
    self.buildtype = "opt"
    self.os = None
    self.platform = None
    self.tree = None
    self.tbfailures = []
    self.suitetype = None
    self.builddate = None
    self.linenumber = 0
    self.testgroup = None
    self.talos = False
    self.talosconfig = None
    self.talossuites = []

  def addBuildProperties(self, resultdict):
    resultdict.update({
      'machine': self.machine,
      'revision': self.revision,
      'buildtype': self.buildtype,
      'platform': self.platform,
      'os': self.os,
      'tree': self.tree,
      'builder': self.builder,
      'starttime': self.starttime,
      'logurl': self.logurl,
    })
    if self.builddate:
      resultdict.update({
        'buildid': self.builddate.strftime('%Y%m%d%H%M%S'),
        'date': self.builddate.strftime('%Y-%m-%d'),
      })
    else:
      resultdict.update({
        'buildid': '20010101000000',
        'date': '2001-01-01',
      })

  def parse(self, fp):
    """
    parse the file, returning a dict of results
    -fp: file-like object

    The result is a dict with the following keys:

    build: the url of the build
    buildtype: 'opt' or 'debug'
    machine: the machine name that the log comes from
    platform: one of 'win32', 'win64', 'linux', 'linux64', 'macosx', 'macosx64'
    repo: the hg repo that the test was run against
    revision: the hg revision that the test was run against
    tinderboxfailures: a list of strings representing tinderbox error
                       messages, if any
    testruns: a list of testruns contained in the log, see
              TestSuiteLogParser.result() for more details
    """

    # step through file one line at a time
    #for line in fp:
    while 1:
      line = fp.readline()
      self.linenumber += 1
      if not line:
        break
      line = line.rstrip()

      # look for tinderbox failures
      for err in self.tberrs:
        if err in line:
          self.tbfailures.append(line.rstrip())
          continue

      # look for the log url
      if not self.logurl:
        m = self.logUrlRe.match(line)
        if m:
          self.logurl = m.group(1)
          continue

      # look for the builder
      if not self.builder:
        m = self.builderRe.match(line)
        if m:
          self.builder = m.group(1)
          m = self.testgroupRe.match(self.builder)
          if m:
            self.testgroup = m.group(6)
            self.tree = m.group(1)
            self.os = m.group(2)
            if 'debug' in self.builder:
              self.buildtype = 'debug'
            elif 'pgo' in self.builder:
              self.buildtype = 'pgo'
            self.platform = AutologTestGroup.get_platform_from_os(self.os)
          continue

      # look for starttime
      if not self.starttime:
        m = self.starttimeRe.match(line)
        if m:
          self.starttime = m.group(1)
          continue

      # look for a revision number
      if not self.revision:
        m = self.revisionRe.match(line)
        if m:
          # sometimes the revision can contain 12 or 24 extra digits (why?);
          # we ignore any beyond the first 12
          self.revision = m.group(1)[0:12]
          continue

      # look for machine name
      if not self.machine:
        m = self.machineRe.match(line)
        if m:
          self.machine = m.group(2)
          continue

      # look for buildid, convert to build date
      if not self.builddate:
        m = self.buildIdRe.match(line)
        if m:
          tmpdate = m.group(1)
          if len(tmpdate) != 14:
            continue
          self.builddate = datetime.datetime(int(tmpdate[0:4]),
                                             int(tmpdate[4:6]),
                                             int(tmpdate[6:8]),
                                             int(tmpdate[8:10]),
                                             int(tmpdate[10:12]),
                                             int(tmpdate[12:14]))
          continue

      # look for build url
      if not self.build:
        m = self.buildRe.match(line)
        if m:
          self.build = m.group(1)
          continue

      # look for talos configuration command indicating it is a talos test
      m = self.talosConfigRe.match(line)
      if m:
        self.talos = True
        self.talosconfig = m.group(0).rstrip()
        continue


      if self.talos:
        # check for start of talos test run
        m = self.talosTestRe.match(line)
        if m:
          testname = m.group(1)
          suiteparser = TalosLogParser(builddate=self.builddate,
                                       linenumber=self.linenumber,
                                       tree=self.tree,
                                       testname=testname)
          (self.linenumber, testdat) = suiteparser.parse(fp)
          self.addBuildProperties(testdat)
          self.talossuites.append(testdat)
          suiteparser = None
          continue

      # look for the command which executes an individual test run
      m = self.mochitestRe.match(line)
      if m:
        self.suitetype = 'mochitest'
      else:
        m = self.reftestRe.match(line)
        if m:
          self.suitetype = 'reftest'
        else:
          m = self.xpcshellRe.match(line)
          if m:
            self.suitetype = 'xpcshell'
      if self.suitetype:
        # store the command-line, then instantiate a test suite parser
        # and parse the section of the log containing that test run; after
        # that parser is done, parsing will resume here
        cmdline = m.group(0).rstrip()
        suiteparser = self.parsers.get(self.suitetype, 
                              TestSuiteLogParser)(cmdline=cmdline,
                                                  includePass=self.includePass,
                                                  builddate=self.builddate,
                                                  linenumber=self.linenumber,
                                                  tree=self.tree)
        (self.linenumber, testdat) = suiteparser.parse(fp)
        testdat.update({ 'cmdline': cmdline })
        self.addBuildProperties(testdat)
        self.testruns.append(testdat)
        self.suitetype = None
        suiteparser = None

    # return the total result as a dict
    # log is from talos
    testgroup = { 'buildurl': self.build }
    if self.talossuites:
      testgroup.update({ 'talossuites' : self.talossuites,
                         'talossuite_count' : len(self.talossuites),
                         'talosconfig' : self.talosconfig,
                         'testgroup': self.testgroup,
                       })
    # log is not talos
    else:
      testgroup.update({ 'buildurl': self.build,
                         'tessuite_count': len(self.testruns),
                         'testgroup': self.testgroup,
                         'testsuites': self.testruns,
                         'frameworkfailures': self.tbfailures if len(self.tbfailures) else None,
                       })
    self.addBuildProperties(testgroup)

    return (self.linenumber, testgroup)

