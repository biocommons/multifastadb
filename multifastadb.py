# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

"""
MultiFastaDB presents a collection of indexed fasta files as a single
source.  The intent is to simplify accessing a virtual database of
sequences that is distributed across multiple files.


>>> from multifastadb import MultiFastaDB

The simplest use is by passing a list of files or directories:

>>> mfdb = MultiFastaDB(['tests/data/ncbi'])

By default, MultiFastaDB looks for files ending in .fasta, .fa, .faa,
.fna, and compressed versions of these ending in .gz.  (NOTE: One
*must* use bgzip for compression; using gzip will fail on reading.)

Fasta files from NCBI contain multiple identifiers for a single
sequence encoded in the accession line, such as
(gi|53292629|ref|NP_001005405.1|).  Optionally, MultiFastaDB will
create a meta index to the ref entries:

>>> mfdb = MultiFastaDB(['tests/data/ncbi'], use_meta_index=True)

Sequences may be retrieved by the `fetch()` method, with optional
sequence start and end bounds (in 0-based or interbase coordinates):

>>> seq = mfdb.fetch('NP_001005405.1')
>>> seq = mfdb.fetch('NP_001005405.1',0,10)

NOTE: Fetching subsequences with bounds is much more efficient than:

>>> seq = mfdb.fetch('NP_001005405.1')[0:10]    # Don't do this!

If a sequence occurs more than once, only the first version is
returned (intentionally).

Attribute-based retrieval is also supported:

>>> seq = mfdb['NP_001005405.1']
>>> seq = mfdb['NP_001005405.1'][0:10]

Attribute-based retrieval does not fetch any sequence
immediately. Instead it returns a SequenceProxy object that fetches
sequence lazily and transparently.  This is particularly useful for
accessing large sequences (e.g., chromosomes).

The locations of a given accession may be found with the `where_is()` method:

>>> mfdb.where_is('gi|53292629|ref|NP_001005405.1|')   # doctest: +ELLIPSIS
[('tests/data/ncbi/f1.human.protein.small.faa.gz', <pysam.cfaidx.Fastafile object at ...>)]

"""


import collections
import itertools
import logging
import os
import re

from ordered_set import OrderedSet
import pysam
import six


_logger = logging.getLogger()


# TODO: clarify bad key and bad coords behavior (raise v. '' v. None)

class MultiFastaDB(object):
    """
    """

    class SequenceProxy(object):

        """represents a future sequence fetch

        SequenceProxy defers the actual fetch until a slice is
        applied, allowing convenient and sexy slice syntax like this:

        >> mfdb = MultiFastaDB('/my/seqs')
        >> seq = mfdb['NM_01234.5'][4:20]

        """

        def __init__(self, mfdb, ac):
            self.mfdb = mfdb
            self.ac = ac

        def __getitem__(self, key):
            if isinstance(key, slice):
                return self.mfdb.fetch(self.ac, key.start, key.stop)[::key.step]
            raise TypeError("SequenceProxy accepts only slice intervals (in interbase coordinates)")

        def __str__(self):
            return self.mfdb.fetch(self.ac)


    # Files must be fasta formatted with one of the following standard
    # fasta file extensions, or a block gzipped version of these
    # (which is supported by pysam >=0.8.3).  For block gzipped files,
    # use the bgzip tool provided with tabix. Standard gzip'd files do
    # NOT work with samtools, and we're requiring users to rename to
    # decrease confusion.
    # See http://samtools.sourceforge.net/tabix.shtml
    file_suffixes = ['fa', 'fasta', 'faa', 'fna']
    compression_suffixes = ['bgz']
    default_suffixes = file_suffixes + [fs + "." + cs
                                        for fs,cs in itertools.product(file_suffixes,compression_suffixes)]


    def __init__(self, sources=[], suffixes=default_suffixes, use_meta_index=False):
        self._fastas = None
        self._index = None
        self._logger = logging.getLogger(__name__)
        self.sources = sources
        self.suffixes = ["." + sfx for sfx in suffixes]
        self.use_meta_index = use_meta_index
        self.open_sources()


    def open_sources(self):
        """Opens or reopens fasta sources (directories or files) provided when
        the instance was created.

        """

        def _has_valid_suffix(f):
            return any(f.endswith(sfx) for sfx in self.suffixes)

        def _find_files(sources):
            for s in sources:
                if os.path.isfile(s):
                    yield s
                    continue
                if os.path.isdir(s):
                    for r, _, fs in os.walk(s, followlinks=True):
                        for f in sorted(fs):
                            if _has_valid_suffix(f):
                                yield os.path.join(r, f)
                    continue
                raise IOError(s + ": invalid or non-existent source for fasta files")

        def _open1(fa_path):
            fai_path = fa_path + '.fai'
            if (os.path.exists(fai_path) and os.stat(fa_path).st_mtime > os.stat(fai_path).st_mtime):
                self._logger.warn(fai_path + " is out-of-date (older than fasta file)")
            faf = pysam.Fastafile(fa_path)    
            self._logger.info("opened " + fa_path)
            return faf

        fa_paths = OrderedSet(os.path.realpath(f) for f in _find_files(self.sources))


        self._fastas = collections.OrderedDict(
            (fa_path, _open1(fa_path)) for fa_path in fa_paths)

        self.create_index()


    def create_index(self):
        """Create a convenience meta index in which secondary accessions refer
        to primary accessions that occur in the fasta file. 

        For example, the primary accession
        'gi|548923668|ref|NM_001284401.1|' would generate two
        secondary accessions '548923668' and 'NM_001284401.1', and two
        tuples ('548923668', 'gi|548923668|ref|NM_001284401.1|') and
        ('NM_001284401.1', 'gi|548923668|ref|NM_001284401.1|') in the
        meta index. Attempts to lookup a secondary accession return
        the sequence for the corresponding primary accession.

        """
        self._index = collections.OrderedDict()
        ncbi_re = re.compile('(?:ref|gb)\|([^|]+)')
        for ref in self.references:
            acs = [ref]
            if self.use_meta_index:
                acs += ncbi_re.findall(ref)
            for ac in acs:
                if ac not in self._index:
                    self._index[ac] = ref
                else:
                    files = [e[0] for e in self.where_is(ac)]
                    self._logger.debug('multiple entries found for {ac} in {files}'.format(
                        ac=ac, files=', '.join(files)))


    def where_is(self, ac):
        """return list of all (filename,pysam.Fastafile) pairs in which
        accession occurs

        TODO: This is broken for meta index lookups
        """
        return [(fp, fh)
                for fp, fh in six.iteritems(self._fastas)
                if ac in fh]


    @property
    def references(self):
        return list(itertools.chain.from_iterable([
            fa.references for fa in self._fastas.values()]))

        
    @property
    def lengths(self):
        return list(itertools.chain.from_iterable([
            fa.lengths for fa in self._fastas.values()]))


    def fetch(self, ac, start_i=None, end_i=None):
        """return a sequence, or subsequence if start_i and end_i are provided"""
        # TODO: should use whereis
        # TODO: should fetch always use a proxy for consistency?
        for fah in self._fastas.values():
            try:
                return fah.fetch(self._index[ac], start_i, end_i)
            except KeyError:
                pass
        # TODO: return KeyError instead
        return None


    def __contains__(self, ac):
        return any([ac in fh for fh in self._fastas.itervalues()])


    def __getitem__(self, ac):
        return self.SequenceProxy(self, ac) if ac in self._index else None


## <LICENSE>
## Copyright 2014 project contributors (https://bitbucket.org/biocommons/multifastadb)
## 
## Licensed under the Apache License, Version 2.0 (the "License");
## you may not use this file except in compliance with the License.
## You may obtain a copy of the License at
## 
##     http://www.apache.org/licenses/LICENSE-2.0
## 
## Unless required by applicable law or agreed to in writing, software
## distributed under the License is distributed on an "AS IS" BASIS,
## WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
## See the License for the specific language governing permissions and
## limitations under the License.
## </LICENSE>
