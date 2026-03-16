import numpy as np
import random
import logging
import math

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a simple multilayer perceptron
class MultilayerPerceptron:
    def __init__(self, input_dim, hidden_dim, output_dim):
        self.weights1 = np.random.rand(input_dim, hidden_dim)
        self.weights2 = np.random.rand(hidden_dim, output_dim)
        self.bias1 = np.zeros((1, hidden_dim))
        self.bias2 = np.zeros((1, output_dim))

    def sigmoid(self, x):
        return 1 / (1 + np.exp(-x))

    def forward(self, inputs):
        hidden_layer = self.sigmoid(np.dot(inputs, self.weights1) + self.bias1)
        output_layer = self.sigmoid(np.dot(hidden_layer, self.weights2) + self.bias2)
        return output_layer

    def train(self, inputs, targets, learning_rate):
        hidden_layer = self.sigmoid(np.dot(inputs, self.weights1) + self.bias1)
        output_layer = self.sigmoid(np.dot(hidden_layer, self.weights2) + self.bias2)

        output_error = targets - output_layer
        hidden_error = np.dot(output_error, self.weights2.T)

        self.weights2 += learning_rate * np.dot(hidden_layer.T, output_error)
        self.bias2 += learning_rate * np.sum(output_error, axis=0, keepdims=True)

        self.weights1 += learning_rate * np.dot(inputs.T, hidden_error)
        self.bias1 += learning_rate * np.sum(hidden_error, axis=0, keepdims=True)

# Generate mock data
def generate_data(num_samples, input_dim, output_dim):
    inputs = np.random.rand(num_samples, input_dim)
    targets = np.random.rand(num_samples, output_dim)
    return inputs, targets

# Main function
def main():
    input_dim = 10
    hidden_dim = 20
    output_dim = 5
    num_samples = 100
    learning_rate = 0.1

    mlp = MultilayerPerceptron(input_dim, hidden_dim, output_dim)
    inputs, targets = generate_data(num_samples, input_dim, output_dim)

    for i in range(100):
        mlp.train(inputs, targets, learning_rate)
        logger.info(f"Iteration {i+1}")

    logger.info("Training complete")
    logger.info(f"Final output: {mlp.forward(inputs)}")

if __name__ == "__main__":
    main()