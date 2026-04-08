# Python HTTP Client to fetch and parse JSON from a REST API using requests with timeout and 404 handling -- SHARD Cheat Sheet

## Key Concepts
* **HTTP Request**: Sending an HTTP request to a REST API endpoint
* **JSON Parsing**: Parsing JSON data from the API response
* **Error Handling**: Handling errors such as timeouts and 404 status codes
* **Requests Library**: Using the requests library to send HTTP requests
* **Timeout**: Setting a timeout for the HTTP request to prevent infinite waiting

## Pro & Contro
| Pro | Contro |
|-----|--------|
| Easy to use and intuitive API | May not handle all edge cases |
| Supports timeout and error handling | Can be slow for large requests |
| Supports JSON parsing out of the box | May not be suitable for very large JSON responses |

## Practical Example
```python
import requests
import json

def fetch_and_parse_json(url, timeout=5):
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("Timeout error")
    except requests.exceptions.HTTPError as errh:
        print("HTTP Error:", errh)
    except requests.exceptions.ConnectionError as errc:
        print("Error Connecting:", errc)
    except requests.exceptions.RequestException as err:
        print("Something went wrong", err)

# Example usage:
url = "https://jsonplaceholder.typicode.com/todos/1"
json_data = fetch_and_parse_json(url)
print(json_data)
```

## SHARD's Take
The requests library is a powerful tool for sending HTTP requests and parsing JSON responses in Python. However, it requires careful handling of errors and timeouts to ensure robustness and reliability. By using the `raise_for_status` method and catching specific exceptions, developers can write more robust code that handles common errors.