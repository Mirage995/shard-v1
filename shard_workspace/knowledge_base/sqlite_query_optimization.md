# sqlite query optimization — SHARD Cheat Sheet

## Key Concepts
- **LIMIT**: Restricts the number of rows returned by a query.
- **OFFSET**: Skips a specified number of rows before starting to return rows from a query.
- **Query Execution Time**: Measures how long it takes for a database query to execute, which is crucial for performance optimization.
- **Indexing**: Improves data retrieval speed by creating an ordered list of values in the table.
- **R-tree Index**: Optimizes spatial queries on geographic or other spatial data.
- **Keyset Pagination (Cursor-Based Pagination)**: Efficiently retrieves subsets of large datasets using a cursor or keyset.
- **Covering Indexes**: Reduces query execution time by storing all required data within the index, eliminating table access.
- **Materialized Views**: Precomputed views that store results of complex queries for faster retrieval.
- **Window Functions (ROW_NUMBER())**: Perform calculations across related rows in a dataset.

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Improves query performance and reduces response time. | Can lead to increased storage requirements if not managed properly. |
| Facilitates efficient data retrieval, especially for large datasets. | May complicate queries when used improperly or over-indexed. |
| Optimizes spatial queries on geographic data. | Can be complex to implement and maintain. |
| Provides a more efficient way to handle pagination in large datasets. | May not always provide the most intuitive user experience. |
| Reduces query execution time by avoiding table access. | Requires careful design to ensure effectiveness. |
| Simplifies complex queries with precomputed views. | Can lead to stale data if not updated regularly. |
| Enables advanced calculations across related rows in a dataset. | May require additional resources for computation and storage. |

## Practical Example
```sql
-- Using LIMIT and OFFSET for pagination
SELECT * FROM users ORDER BY id LIMIT 10 OFFSET 20;

-- Creating an index on a column to improve query performance
CREATE INDEX idx_users_name ON users(name);

-- Using R-tree index for spatial queries
CREATE VIRTUAL TABLE locations USING rtree(id, lat, lon);
INSERT INTO locations (id, lat, lon) VALUES (1, 34.0522, -118.2437);
SELECT * FROM locations WHERE lat BETWEEN 34 AND 35 AND lon BETWEEN -119 AND -117;
```

## SHARD's Take
SQLite query optimization is essential for improving database performance and user experience. By understanding concepts like indexing, pagination techniques, and window functions, developers can create more efficient and effective queries that handle large datasets with ease.