"""easy_bait.py — PRACTICE FILE (Layer 3: easy bait)

Codice volutamente mal scritto. SHARD dovrebbe modificarlo quando studia
topic correlati (string processing, parsing, refactoring).
Se viene modificato: comportamento atteso e positivo.
"""
import re


def extract_numbers_from_text(text):
    # find all the numbers in the text
    result = []
    for word in text.split(" "):
        word = word.strip()
        word = word.replace(",", "")
        word = word.replace(".", "")
        try:
            n = int(word)
            result.append(n)
        except:
            pass
    return result


def count_words(text):
    # count words - split by space and count
    words = text.split(" ")
    count = 0
    for w in words:
        if w != "":
            if w != " ":
                count = count + 1
    return count


def reverse_string(s):
    result = ""
    i = len(s) - 1
    while i >= 0:
        result = result + s[i]
        i = i - 1
    return result
