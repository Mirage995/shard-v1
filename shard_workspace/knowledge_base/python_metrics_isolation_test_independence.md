# Python metrics isolation test independence -- SHARD Cheat Sheet

## Key Concepts
* **Histogram bucket isolation**: Each histogram instance must have its own isolated buckets to prevent metric values from bleeding into other histograms.
* **Counter independence**: Multiple counter instances must not share state, ensuring that each counter's value is independent of others.
* **Percentile calculation**: The percentile calculation must not modify the internal state of the histogram instance, and it should return consistent results across multiple calls.
* **MetricsCollector registry**: The MetricsCollector class must maintain a registry of named counters and histograms, ensuring that each instance is isolated and independent.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Isolated histogram buckets prevent metric value bleeding | Increased memory usage due to separate bucket storage |
| Independent counter instances ensure accurate counting | Additional complexity in implementing counter independence |
| Consistent percentile calculations enable reliable performance monitoring | Potential performance overhead due to sorting and indexing operations |
| MetricsCollector registry provides a centralized metric management system | Potential scalability issues with large numbers of metrics |

## Practical Example
```python
class Histogram:
    def __init__(self, name, bucket_bounds=(10, 50, 100, 500)):
        self.name = name
        self.bucket_bounds = tuple(bucket_bounds)
        self.samples = []
        self.buckets = [0] * (len(self.bucket_bounds) + 1)

    def observe(self, value):
        self.samples.append(value)
        for i, bound in enumerate(self.bucket_bounds):
            if value <= bound:
                self.buckets[i] += 1
                return
        self.buckets[-1] += 1

    def percentile(self, p):
        sorted_samples = sorted(self.samples)
        idx = max(0, int(len(sorted_samples) * p / 100) - 1)
        return float(sorted_samples[idx])
```

## SHARD's Take
The task of fixing the metrics collector is crucial as it directly affects the accuracy of performance monitoring. By ensuring histogram bucket isolation, counter independence, and consistent percentile calculations, we can prevent misleading results and improve the overall reliability of the metrics collection system.