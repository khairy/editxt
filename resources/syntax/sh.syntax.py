# EditXT
# Copyright 2007-2013 Daniel Miller <millerdev@gmail.com>
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

name = "Shell"
filepatterns = ["*.sh"]
comment_token = "#"
word_groups = [
    ("""
        alias
        break
        case
        continue
        done
        elif
        else
        esac
        exec
        exit
        export
        fi
        for
        function
        if
        return
        set
        then
        unalias
        unset
        until
        while
    """.split(), "0000CC"),
    #("&& ||".split(), "000080"),
    #("== !=".split(), "FF0000"),
]
delimited_ranges = [
    (RE('[ru]?"'), ['"', RE(r"[^\\]\n")], "800080", None),
    (RE("[ru]?'"), ["'", RE(r"[^\\]\n")], "008080", None),
    ("#", [RE(r"(?=\n)")], "008000", None),
]
