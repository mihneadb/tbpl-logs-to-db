#!/usr/bin/env python

import os
import sys

from datetime import datetime
from logparser import testsuiteparser, buildlog
from gzip import GzipFile
from peewee import *


#### parsing

parsers = {
    #'build1': buildlog.BuildLogParser,
    'mochitest': testsuiteparser.MochitestParser,
    'reftest': testsuiteparser.ReftestParser,
    'jsreftest': testsuiteparser.ReftestParser,
    'crashtest': testsuiteparser.ReftestParser,
    'xpcshell': testsuiteparser.XPCshellParser,
}

def parse_file(filepath, parser):
    try:
        with GzipFile(filepath) as fp:
            return parser.parse(fp)
    except IOError as e:
        if "CRC check failed" in e.message:
            return None
        raise

def infer_type(filename):
    for harness_type in parsers:
        if harness_type in filename.split('-'):
            return harness_type
    return None # not supported



#### db

db = PostgresqlDatabase('logs')
db.get_conn().set_client_encoding('UTF8')

class BaseModel(Model):
    """A base model that will use our Postgresql database"""
    class Meta:
        database = db

class TestData(BaseModel):
    kind = CharField(index=True)
    slavetype = CharField(index=True)
    testfile = CharField(index=True)
    passed = BooleanField()
    date = DateTimeField()

TestData.create_table(True)

def save_to_db(collection, kind, slavetype, date, passed=True):
    for test in collection:
        data = TestData.get_or_create(
            kind=kind,
            slavetype=slavetype,
            testfile=test['test'],
            passed=passed,
            date=date,
        )

def count_files(root):
    count = 0
    for root, dirs, files in os.walk(root):
        count += len(files)
    return count


if __name__ == '__main__':
    logs_dir = sys.argv[1]

    count = count_files(logs_dir)
    current = 0

    for root, dirs, files in os.walk(logs_dir):
        for filename in files:
            t = infer_type(filename)
            if not t:
                continue
            filepath = os.path.join(root, filename)
            parser = parsers[t](includePass=True)

            result = parse_file(filepath, parser)
            if not result:
                continue
            result = result[1]

            date = datetime.fromtimestamp(result['starttime'])

            save_to_db(result['passes'], t, result['slavetype'], date, True)
            save_to_db(result['failures'], t, result['slavetype'], date, False)

            current += 1
            sys.stdout.write("\tDone: %d/%d\r" % (current, count))
            sys.stdout.flush()

