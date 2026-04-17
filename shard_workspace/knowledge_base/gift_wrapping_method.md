# gift wrapping method -- SHARD Cheat Sheet

## Key Concepts
* The gift wrapping method is a simple algorithm for finding the convex hull of a set of 2D points.
* It works by iteratively adding points to the convex hull in a counterclockwise direction.
* The algorithm starts with the leftmost point and then repeatedly selects the point that is most counterclockwise from the current point.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Simple to implement | Not efficient for large datasets |
| Easy to understand | Does not handle collinear points well |
| Works well for small datasets | Not suitable for high-dimensional data |

## Practical Example
```python
import matplotlib.pyplot as plt
import numpy as np

def gift_wrapping(points):
    n = len(points)
    hull = []
    l = 0
    for i in range(1, n):
        if points[i][0] < points[l][0]:
            l = i

    p = l
    while True:
        hull.append(points[p])
        q = (p + 1) % n

        for i in range(n):
            if orientation(points[p], points[i], points[q]) == 2:
                q = i

        p = q
        if p == l:
            break

    return hull

def orientation(p, q, r):
    val = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if val == 0:
        return 0
    elif val > 0:
        return 1
    else:
        return 2

points = np.random.rand(10, 2)
hull = gift_wrapping(points)

plt.scatter(points[:, 0], points[:, 1])
hull.append(hull[0])
plt.plot([p[0] for p in hull], [p[1] for p in hull], 'r-')
plt.show()
```

## SHARD's Take
The gift wrapping method is a straightforward algorithm for finding the convex hull of a set of 2D points, but its simplicity comes at the cost of efficiency for large datasets. Despite this, it remains a useful tool for small-scale applications and educational purposes. Its implementation is relatively easy to understand and visualize, making it a great introduction to more complex geometric algorithms.