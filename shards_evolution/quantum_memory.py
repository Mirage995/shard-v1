# shards_evolution/quantum_memory.py
import random

class QuantumMemory:
    """
    Classe per l'archiviazione di ricordi multipli in sovrapposizione.
    I ricordi sono rappresentati come stringhe e sono archiviati in una lista.
    Quando viene interrogata, la classe collassa su un solo ricordo casuale.
    """
    def __init__(self):
        """
        Inizializza la memoria quantistica con una lista vuota di ricordi.
        """
        self.memory = []

    def add_memory(self, memory):
        """
        Aggiunge un nuovo ricordo alla memoria quantistica.
        :param memory: il ricordo da aggiungere (stringa)
        """
        self.memory.append(memory)

    def collapse(self):
        """
        Collassa la memoria quantistica su un solo ricordo casuale.
        :return: il ricordo collassato (stringa)
        """
        if not self.memory:
            return None
        return random.choice(self.memory)

    def clear(self):
        """
        Resetta la memoria quantistica senza riallocare l'oggetto.
        """
        self.memory.clear()

    def query(self):
        """
        Interroga la memoria quantistica e collassa su un solo ricordo.
        :return: il ricordo collassato (stringa)
        """
        return self.collapse()

    def __str__(self):
        """
        Restituisce una rappresentazione stringa della memoria quantistica.
        :return: la rappresentazione stringa (stringa)
        """
        return f"QuantumMemory({', '.join(self.memory)})"

# Esempio di utilizzo
if __name__ == "__main__":
    qm = QuantumMemory()
    qm.add_memory("Ricordo 1")
    qm.add_memory("Ricordo 2")
    qm.add_memory("Ricordo 3")
    print("Memoria quantistica:", qm)
    print("Ricordo collassato:", qm.query())