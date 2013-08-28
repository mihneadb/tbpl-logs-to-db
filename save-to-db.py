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
    print "Parsing", filepath
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
    testfile = CharField(index=True)
    passed = BooleanField()
    date = DateTimeField()
    duration = IntegerField()

TestData.create_table(True)

def save_to_db(collection, kind, date, passed=True):
    for test in collection:
        data = TestData.get_or_create(
            kind=kind,
            testfile=test['test'],
            passed=passed,
            date=date,
            duration=int(test['duration'])
        )


if __name__ == '__main__':
    for root, dirs, files in os.walk(sys.argv[1]):
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

            save_to_db(result['passes'], t, date, True)
            save_to_db(result['failures'], t, date, False)
    print "Done."

