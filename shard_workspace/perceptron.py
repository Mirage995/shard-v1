
import numpy as np

class Perceptron:
    def __init__(self, num_inputs, learning_rate=0.01, num_epochs=100):
        self.num_inputs = num_inputs
        self.learning_rate = learning_rate
        self.num_epochs = num_epochs
        # Initialize weights and bias to zeros
        # A fascinating state of equilibrium before collapsing the function wave
        self.weights = np.zeros(num_inputs)
        self.bias = 0

    def activation_func(self, x):
        # Simple step function for a basic perceptron
        return 1 if x >= 0 else 0

    def train(self, X, y):
        print("Training initiated. Collapsing potential states into a definitive model...")
        for epoch in range(self.num_epochs):
            # In a quantum sense, each epoch refines the probability distribution
            for i in range(len(X)):
                prediction = self.predict(X[i])
                error = y[i] - prediction
                # Update weights based on error (the 'collapse' of the error function)
                self.weights += self.learning_rate * error * X[i]
                self.bias += self.learning_rate * error
        print("Training complete. Function waves collapsed successfully.")

    def predict(self, X):
        # Dot product and activation
        linear_output = np.dot(X, self.weights) + self.bias
        return self.activation_func(linear_output)

# --- Dataset: AND gate ---
# Input: [x1, x2], Output: y
X = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
y = np.array([0, 0, 0, 1])

# --- Training ---
perceptron = Perceptron(num_inputs=2, learning_rate=0.01, num_epochs=100)
perceptron.train(X, y)

# --- Testing ---
print("\nTesting model:")
for i in range(len(X)):
    prediction = perceptron.predict(X[i])
    print(f"Input: {X[i]}, Expected: {y[i]}, Predicted: {prediction}")

# Verify accuracy
predictions = [perceptron.predict(x) for x in X]
accuracy = np.mean(predictions == y)
print(f"\nAccuracy: {accuracy * 100}%")
