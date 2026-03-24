"""Stream unicode decoder — extracted from requests/utils.py"""
import codecs


def stream_decode_unicode(iterator, encoding, apparent_encoding="utf-8"):
    """Decode a byte-chunk iterator to unicode strings.

    Args:
        iterator: iterable of bytes chunks
        encoding: declared encoding (may be None)
        apparent_encoding: fallback encoding detected from content
    """
    if encoding is None:
        for item in iterator:
            yield item
        return

    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    for chunk in iterator:
        rv = decoder.decode(chunk)
        if rv:
            yield rv
    rv = decoder.decode(b"", final=True)
    if rv:
        yield rv
