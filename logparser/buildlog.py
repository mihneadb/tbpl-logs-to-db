#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import re

from config import trees_to_watch


class BuildLogParser(object):

  timere = re.compile(r'Started (.*) \(results: (.*?), elapsed: ((((\d+) hrs, )*(\d+) mins, )*(\d+) secs)\)')
  fullbuildre = re.compile(r'Creating directory build$')
  builderre = re.compile(r'builder: (.*)')
  buildernamere = re.compile(r'buildername: (.*)$')
  slavere = re.compile(r'slave: (.*)')
  starttimere = re.compile(r"^starttime: (.*?)\.")
  revisionre = re.compile(r"^revision: (.*)$")
  buildidre = re.compile(r"^buildid: '(\d+)'$")
  typere = re.compile(r'(%s)[-|_](.*?)(-debug|-o-debug)*(-(.*))*$' % '|'.join(trees_to_watch))
  resultsre = re.compile(r'results: (.*)$')
  logurlre = re.compile(r'logurl: (.*)$')
  builddirre = re.compile(r"builddir: '(.*?)'")
  clobberre = re.compile(r'(.*?):Clobbering...')
  purgedeletere = re.compile(r'^Deleting (.*)')

  def __init__(self, **kwargs):
    self.builder = None
    self.slave = None
    self.total = 0.0
    self.linenumber = 0
    self.laststep = None
    self.starttime = None
    self.revision = None
    self.steps = {}
    self.buildid = None
    self.platform = None
    self.tree = None
    self.buildtype = 'opt'
    self.buildname = 'build'
    self.success = None
    self.buildername = None
    self.logurl = None
    self.clobbertype = None
    self.builddir = None
    self.clobbers = []

  def parse(self, fp):

    while True:
      line = fp.readline()
      if not line:
        break
      self.linenumber += 1
      line = line.rstrip()

      if not self.logurl:
        match = self.logurlre.match(line)
        if match:
          self.logurl = match.group(1)
          continue

      if not self.slave:
        match = self.slavere.search(line)
        if match:
          self.slave = match.group(1)
          continue

      if not self.builddir:
        match = self.builddirre.match(line)
        if match:
          self.builddir = match.group(1)
          self.periodicre = re.compile(r'%s:More than 604800.0 seconds have passed since our last clobber' % self.builddir)
          continue

      if not self.buildername:
        match = self.buildernamere.match(line)
        if match:
          self.buildername = match.group(1)
          continue

      if not self.builder:
        match = self.builderre.search(line)
        if match:
          self.builder = match.group(1)
          match = self.typere.match(self.builder)
          if match:
            self.tree = match.group(1)
            self.platform = match.group(2)
            if match.group(3):
              self.buildtype = 'debug'
            if match.group(5):
              self.buildname = match.group(5)
          continue

      if self.success is None:
        match = self.resultsre.match(line)
        if match:
          if 'success' in match.group(1):
            self.success = True
          else:
            self.success = False
          continue

      if not self.starttime:
        match = self.starttimere.search(line)
        if match:
          self.starttime = match.group(1)
          continue

      if not self.revision:
        match = self.revisionre.search(line)
        if match:
          self.revision = match.group(1)[0:12]
          continue

      if not self.buildid:
        match = self.buildidre.search(line)
        if match:
          self.buildid = match.group(1)
          continue

      match = self.timere.search(line)
      if match:
        step = match.group(1)
        if 'hgtool.py' in step:
          step = 'hgtool.py'
        hrs = int(match.group(6)) if match.group(6) else 0
        mins = int(match.group(7)) if match.group(7) else 0
        secs = int(match.group(8)) if match.group(8) else 0
        subtotal = float(hrs * 60) + mins + (float(secs) / 60)
        self.total += subtotal
        self.laststep = step
        if subtotal > 0.5 or 'update' in step or 'hgtool' in step:
          self.steps[step] = '{0:1.2f}'.format(subtotal)

      if self.laststep == 'compile' and self.fullbuildre.search(line) and 'compile' in self.steps:
        self.steps['compile_full'] = self.steps['compile']
        del self.steps['compile']

      if self.laststep == 'set props: purge_actual purge_target':
        match = self.purgedeletere.match(line)
        if match:
          self.clobbers.append(line)
          if self.builddir and self.builddir in line:
            self.clobbertype = 'free space'

      if self.laststep == 'checking clobber times' and self.builddir:
        match = self.periodicre.match(line)
        if match:
          self.clobbertype = 'periodic'
        match = self.clobberre.match(line)
        if match:
          self.clobbers.append(line)

    if 'compile_full' in self.steps and self.clobbertype is None:
      self.clobbertype = 'unknown'

    build = {
      'machine': self.slave,
      'builder': self.builder,
      'buildername': self.buildername,
      'revision': self.revision,
      'starttime': self.starttime,
      'buildid': self.buildid,
      'platform': self.platform,
      'tree': self.tree,
      'success': self.success,
      'buildtype': self.buildtype,
      'buildname': self.buildname,
      'steps': self.steps,
      'logurl': self.logurl,
      'total': '{0:1.2f}'.format(self.total),
      'builddir': self.builddir,
      'clobbertype': self.clobbertype,
      'clobbers': self.clobbers,
    }

    return (self.linenumber, build)
