#! /usr/bin/env python
# EditXT
# Copyright (c) 2007-2010 Daniel Miller <millerdev@gmail.com>
# 
# This file is part of EditXT, a programmer's text editor for Mac OS X,
# which can be found at http://editxt.org/.
# 
# EditXT is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# EditXT is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with EditXT.  If not, see <http://www.gnu.org/licenses/>.
import logging
import sys
import timeit

sys.path.append("src")
import sitelibs

logging.basicConfig(
    format='%(levelname)s - %(message)s',
    level=logging.DEBUG
)
log = logging.getLogger("test")

def eq(v0, v1):
    if v0 != v1:
        print "WARNING trial cases do not yield equal results"
        print v0
        print v1
        print

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# prime generator

init = """
import itertools

def prime_gen_0():
    yield 2
    n = 3
    yield n
    prime_list = [(2, 4), (3, 9)]
    it = itertools.count(4)
    for n in it:
        n = it.next()
        for p,p2 in prime_list:
            if n % p == 0:
                break
            elif p2 > n:
                prime_list.append((n, n*n))
                yield n
                break
        else:
            raise RuntimeError("Shouldn't have run out of primes!")


def prime_gen_1():
    prime_list = [2, 3]
    for p in prime_list: yield p
    for n in itertools.count(prime_list[-1] + 2):
        for p in prime_list:
            if p * p > n:
                prime_list.append(n)
                yield n
                break
            elif n % p == 0:
                break
        else:
            raise Exception("Shouldn't have run out of primes!")

pg0 = prime_gen_0()
pg1 = prime_gen_1()

"""

trials = [

"[pg0.next() for i in xrange(1000)]",

"[pg1.next() for i in xrange(1000)]",

]
n = 50

# trial 0: 4.21483492851
# trial 1: 0.391325950623

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

try:
    exec init
    v0 = eval(trials[0])
    v1 = eval(trials[1])
    eq(v0, v1)
except Exception:
    log.error("trial equality test failed", exc_info=True)
    print

for i, trial in enumerate(trials):
    t = timeit.Timer(trial, init)
    v1 = t.timeit(n)
    print "# trial %i:" % i, v1

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

'''
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# string.rfind(u"\n", ...) vs NSString.lineRangeForRange_(...).location

init = """
from Foundation import NSString

us = (u"a " * 400 + u"\\n") * 3000
ns = NSString.stringWithString_(us)

indices = [20, 300, 799, 1200, 2000 * 800, 2000 * 800 + 400, 3000 * 800 - 2, 3000 * 800 - 400]
"""

trials = [

"""
[ns.rfind(u"\\n", 0, i) + 1 for i in indices]
""",

"""
[ns.lineRangeForRange_((i, 0)).location for i in indices]
""",

]
n = 100000

# trial 0: 1.40011692047
# trial 1: 7.51187491417

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# while-loop-search vs NSString.lineRangeForRange_(...).location

init = """
from Foundation import NSString

us = (u"a " * 400 + u"\\n") * 3000
ns = NSString.stringWithString_(us)

indices = [20, 300, 799, 1200, 2000 * 800, 2000 * 800 + 400, 3000 * 800 - 2, 3000 * 800 - 400]

def find0(text, i):
    while i > 0 and text[i-1] not in u"\\n\\r\\u2028":
        i -= 1
    return i

def find1(text, i):
    return text.lineRangeForRange_((i, 0)).location

"""

trials = [

"[find0(ns, i) for i in indices]",

"[find1(ns, i) for i in indices]",

]
n = 5000

# trial 0: 4.21483492851
# trial 1: 0.391325950623

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# NSRange.location/.length vs subscript notation

init = """
from Foundation import NSMakeRange

r = NSMakeRange(0, 2)
"""

trials = [

"r[0], r[1]",

"r.location, r.length",

]
n = 1000000

# trial 0: 0.246095895767
# trial 1: 0.268185138702

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
'''
