import os
import sys
try:
  import json
except:
  import simplejson as json
import optparse
from subprocess import Popen, PIPE, STDOUT

def listToDict(l1):
  count = 0
  d = {}
  for item in l1:
    d.update({'listitem_' + str(count): item})
    count += 1
  return d

def dict_diff(first, second):
  diff = {}
  KEYNOTFOUND = '<keynotfound>'
  for key in first.keys():
    if (not second.has_key(key)):
        diff[key] = (first[key], KEYNOTFOUND)
    elif type(first[key]) == type(dict()):
      adiff = dict_diff(first[key], second[key])
      if adiff:
        diff[key] = adiff
    elif first[key] != second[key]:
      diff[key] = (first[key], second[key])
  for key in second.keys():
    if (not first.has_key(key)):
      diff[key] = (KEYNOTFOUND, second[key])
  
  return diff

def getDiffs(dd1, dd2):
  d1 = listToDict(dd1)
  d2 = listToDict(dd2)
  return dict_diff(d1, d2)

def runtest(testfile, reffile, update):
  thisdir = os.path.dirname(os.path.abspath(__file__))
  outputlog = os.path.join(thisdir, 'outfile')
  cmd = [sys.executable,
         os.path.join(thisdir, 'logparser.py'),
         testfile]

  outfile = open(outputlog, 'w')
  p = Popen(cmd, stdout=outfile, stderr=STDOUT)
  outfile.close()
  retcode = p.wait()
  
  test_fp = open(outputlog, 'rb')
  test = json.loads(test_fp.read())
  test_fp.close()

  ref_fp = open(reffile, 'rb')
  ref = json.loads(ref_fp.read())
  ref_fp.close()

  if ref == test:
    print 'TEST-PASS | ' + os.path.basename(testfile)
  else:
    if update:
      print "updating %s" % reffile
      ref_fp = open(reffile, 'wb')
      for line in test:
        ref_fp.write(json.dumps(line) + '\n')
      ref_fp.close()
    else:
      print 'TEST-UNEXPECTED-FAIL | ' + os.path.basename(testfile)
      print getDiffs(test, ref)

def main():
  """Run logparser tests.  All tests are assumed to be in the 'tests'
     directory; each test consists of a logfile with a '.log' or '.log.gz'
     extension, and a corresponding reference, ending in '-output.txt',
     containing expected output.
  """

  testdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tests')

  parser = optparse.OptionParser()
  parser.add_option("--update",
                    action = "store_true", dest = "update",
                    default = False,
                    help = "update the test references")
  (options, args) = parser.parse_args()

  for root, dirs, files in os.walk(testdir):
    for file in files:
      if '.log' in file:
        ref = "%s-output.txt" % file[0:file.find('.log')]
        if ref in files:
          runtest(os.path.join(testdir, file),
                  os.path.join(testdir, ref),
                  options.update)
        else:
          pass
          #print 'TEST-UNEXPECTED-FAIL | file ' + file + ' has no reference for testtype ' + testtype

if __name__ == '__main__':
  main()
