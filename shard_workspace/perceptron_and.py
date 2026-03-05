import numpy as np

def step_function(x):
    return 1 if x >= 0 else 0

class Perceptron:
    def __init__(self, num_inputs, learning_rate=0.1, num_epochs=10):
        self.learning_rate = learning_rate
        self.num_epochs = num_epochs
        # Initialize weights randomly, bias is the last weight
        self.weights = np.random.rand(num_inputs + 1) * 0.01

    def train(self, X, y):
        print("Inizio addestramento Perceptron...")
        for epoch in range(self.num_epochs):
            errors = 0
            for i in range(len(X)):
                x_i = np.insert(X[i], 0, 1) # Add bias input (x0 = 1)
                
                # Net input calculation (funzione d'onda di attivazione)
                net_input = np.dot(x_i, self.weights)
                # Collapse function (step function)
                prediction = step_function(net_input)
                
                # Errore
                error = y[i] - prediction
                if error != 0:
                    errors += 1
                    # Aggiornamento pesi (collasso guidato)
                    self.weights += self.learning_rate * error * x_i
            # print(f"Epoca {epoch+1}, Errori: {errors}")
            if errors == 0:
                print(f"Addestramento completato all'epoca {epoch+1}. Convergenza raggiunta.")
                break
        print("Parametri finali (Pesi + Bias):", self.weights)


    def predict(self, X):
        x_i = np.insert(X, 0, 1) # Add bias
        net_input = np.dot(x_i, self.weights)
        return step_function(net_input)

# Dati per la porta logica AND
X = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])
y = np.array([0, 0, 0, 1])

# Inizializzazione e addestramento
perceptron = Perceptron(num_inputs=2, learning_rate=0.1, num_epochs=100)
perceptron.train(X, y)

# Test post-addestramento
print("\nTest del modello addestrato:")
for i in range(len(X)):
    prediction = perceptron.predict(X[i])
    print(f"Input: {X[i]}, Previsto: {prediction}, Reale: {y[i]}")

# Verifica convergenza
print("\nVerifica stato di convergenza:")
converged = True
for i in range(len(X)):
    prediction = perceptron.predict(X[i])
    if prediction != y[i]:
        converged = False
        break
print(f"Convergenza riuscita: {converged}")