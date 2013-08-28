# some configuration parameters for logparser

__all__ = ['platform_list', 'test_list', 'trees_to_watch']

# a list of platforms for which to process log files
platform_list = ['linux', 'linux64', 'win32', 'win64', 'macosx', 'macosx64',
                 'w764', 'android', 'android-noion',
                 'android-armv6', 'ics_armv7a_gecko']

# a list of test types for which to process log files
test_list = ['reftest', 'jsreftest', 'xpcshell', 'mochitests-1',
             'mochitests-2', 'mochitests-3', 'mochitests-4', 'mochitests-5',
             'mochitest-browser-chrome', 'mochitest-other', 'crashtest', 'crashtest-ipc',
             'reftest-ipc', 'paint', 'svg', 'chrome', 'chrome_mac', 'tp',
             'nochrome', 'dromaeo', 'dirty', 'v8', 'xperf',
             'mochitest-1', 'mochitest-2', 'mochitest-3', 'mochitest-4',
             'mochitest-5', 'mochitest-6', 'mochitest-7', 'mochitest-8',
             'browser-chrome', 'crashtest-1', 'crashtest-2',
             'jsreftest-1', 'jsreftest-2', 'jsreftest-3', 'reftest-1',
             'reftest-2', 'remote-tdhtml', 'remote-tpan', 'remote-tsspider',
             'remote-tsvg', 'remote-tp4m', 'remote-tp4m_nochrome',
             'remote-ts', 'remote-twinopen', 'remote-tzoom'
            ]

# parse logs from these trees
trees_to_watch = ['mozilla-central',
                  'mozilla-inbound',
                  'build-system',
                  'fx-team',
                  'ionmonkey',
                  'profiling',
                  'services-central',
                  'mozilla-aurora',
                  'mozilla-beta',
                  'mozilla-b2g18',
                  'mozilla-esr17'
                 ]
