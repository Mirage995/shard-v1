# dns resolution python — SHARD Cheat Sheet

## Key Concepts
* DNS Resolution: Translating domain names into IP addresses.
* `dnspython`: A Python library for performing DNS queries.
* A Record: Maps a hostname to an IPv4 address.
* MX Record: Specifies mail servers for a domain.
* CNAME Record: Creates an alias for a domain name.
* DNS Resolver: A system that performs DNS lookups.
* `NXDOMAIN`: A DNS error indicating the domain does not exist.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple to use with `dnspython` | Can be slow due to network latency |
| Allows programmatic DNS lookups | Requires error handling for network issues and invalid domains |
| Supports various record types (A, MX, CNAME) | Relies on external DNS servers, which might be unreliable |

## Practical Example
```python
import dns.resolver

def resolve_domain(domain_name):
    try:
        resolver = dns.resolver.Resolver()
        answers = resolver.resolve(domain_name, 'A')
        for rdata in answers:
            print(f"IP Address: {rdata.address}")
    except dns.resolver.NXDOMAIN:
        print(f"Domain {domain_name} does not exist.")
    except dns.resolver.Timeout:
        print("DNS query timed out.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    resolve_domain("google.com")
```

## SHARD's Take
`dnspython` simplifies DNS resolution in Python, enabling programmatic access to DNS information. However, robust error handling is crucial to manage potential network issues and invalid domain names. Understanding DNS record types is essential for interpreting the results.