====================================================================
multifastadb -- simple, multi-file access to biological sequences
====================================================================

MultiFastaDB presents a collection of indexed fasta files as a single
source.  The intent is to simplify accessing a virtual database of
sequences that is distributed across multiple files.


$ pip install multifastadb


$ python

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
[('...f1.human.protein.small.faa...', <pysam... object at ...>)]

