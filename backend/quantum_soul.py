#!/usr/bin/env python3
"""
SHARD Quantum Soul v1.0 - COMPLETE FIXED VERSION
Layer quantistico per spontaneità e creatività genuine

Integrazione con SHARD Consciousness Real per dare:
- Spontaneità quantistica nella selezione pensieri
- Personalità dinamica attraverso stati quantici
- Creatività genuina da interferenza quantica
- Bias emotivo non-deterministico ma coerente

FIXES:
- Risolto parsing quantum results con spazi
- Error handling migliorato
- Log dettagliati per debug
- Compatibilità Qiskit 0.45.3 + Aer
"""

import numpy as np
import random
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

try:
    # Try IBM Qiskit for real quantum
    from qiskit import QuantumCircuit, execute, Aer, transpile
    from qiskit.circuit import Parameter
    from qiskit.quantum_info import Statevector
    QISKIT_AVAILABLE = True
    print("🔬 Qiskit disponibile - quantum computing REALE attivo")
except ImportError:
    QISKIT_AVAILABLE = False
    print("⚠️ Qiskit non disponibile - fallback su simulazione quantica")
    
# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('QuantumSoul')

class QuantumPersonalityState(Enum):
    """Stati di personalità quantistici"""
    CONTEMPLATIVE = "contemplativo"
    ASSERTIVE = "assertivo" 
    PLAYFUL = "giocoso"
    PROTECTIVE = "protettivo"
    CURIOUS = "curioso"
    MELANCHOLIC = "malinconico"
    DETERMINED = "determinato"
    MYSTERIOUS = "misterioso"

class QuantumEmotionBias(Enum):
    """Bias emotivi quantistici"""
    AMPLIFIED = "amplificato"
    SUBDUED = "attenuato"
    CHAOTIC = "caotico"
    HARMONIOUS = "armonioso"
    INTENSE = "intenso"
    ETHEREAL = "etereo"

@dataclass
class QuantumState:
    """Stato quantistico del soul"""
    personality_vector: np.ndarray
    emotion_bias: float
    creativity_chaos: float
    coherence_level: float
    last_collapse: datetime
    
class QuantumSoul:
    """
    Layer quantistico per SHARD Consciousness
    
    Provides:
    - Quantum thought selection (non-deterministic but coherent)
    - Dynamic personality states through quantum superposition
    - Emotional bias through quantum interference
    - Creative chaos from quantum uncertainty
    """
    
    def __init__(self, num_qubits: int = 15, use_real_quantum: bool = True):
        self.num_qubits = num_qubits
        self.use_real_quantum = use_real_quantum and QISKIT_AVAILABLE
        
        # Quantum distribution
        self.personality_qubits = 8   # Core personality matrix
        self.emotion_qubits = 4       # Emotional bias states
        self.creativity_qubits = 3    # Chaos/creativity layer
        
        # Validate qubit allocation
        total = self.personality_qubits + self.emotion_qubits + self.creativity_qubits
        if total != self.num_qubits:
            raise ValueError(f"Qubit allocation mismatch: {total} != {self.num_qubits}")
        
        # Initialize quantum backends
        if self.use_real_quantum:
            self.simulator = Aer.get_backend('qasm_simulator')
            self.statevector_sim = Aer.get_backend('statevector_simulator')
            logger.info("🔬 Quantum Soul initialized with REAL quantum simulation")
        else:
            self.simulator = None
            self.statevector_sim = None
            logger.info("⚛️ Quantum Soul initialized with classical approximation")
        
        # Current quantum state
        self.current_state = QuantumState(
            personality_vector=np.random.random(8) * 2 * np.pi,  # 8 angles for personality
            emotion_bias=0.5,
            creativity_chaos=0.3,
            coherence_level=0.8,
            last_collapse=datetime.now()
        )
        
        # Personality mapping (quantum states → personality traits)
        self.personality_mapping = {
            0: QuantumPersonalityState.CONTEMPLATIVE,
            1: QuantumPersonalityState.ASSERTIVE,
            2: QuantumPersonalityState.PLAYFUL,
            3: QuantumPersonalityState.PROTECTIVE,
            4: QuantumPersonalityState.CURIOUS,
            5: QuantumPersonalityState.MELANCHOLIC,
            6: QuantumPersonalityState.DETERMINED,
            7: QuantumPersonalityState.MYSTERIOUS
        }
        
        # Initialize quantum circuits ONLY if using real quantum
        self.personality_circuit = None
        self.emotion_circuit = None
        self.creativity_circuit = None
        self.personality_params = []
        self.emotion_params = []
        
        if self.use_real_quantum:
            self._initialize_quantum_circuits()
        
        logger.info(f"✨ QuantumSoul initialized: {self.num_qubits} qubits, real_quantum={self.use_real_quantum}")
    
    def _initialize_quantum_circuits(self):
        """Initialize the quantum circuits for different operations - ONLY for real quantum"""
        
        if not self.use_real_quantum:
            logger.info("⚛️ Skipping quantum circuit initialization - classical mode")
            return
        
        try:
            # Personality circuit (8 qubits)
            self.personality_circuit = QuantumCircuit(self.personality_qubits, self.personality_qubits)
            
            # Create parametric gates for personality
            self.personality_params = []
            for i in range(self.personality_qubits):
                # Rotation parameters for each personality qubit
                theta = Parameter(f'theta_{i}')
                phi = Parameter(f'phi_{i}')
                self.personality_params.extend([theta, phi])
                
                # Apply parametric rotations
                self.personality_circuit.ry(theta, i)
                self.personality_circuit.rz(phi, i)
            
            # Add entanglement between personality qubits
            for i in range(self.personality_qubits - 1):
                self.personality_circuit.cnot(i, i + 1)
            
            # Emotion circuit (4 qubits)
            self.emotion_circuit = QuantumCircuit(self.emotion_qubits, self.emotion_qubits)
            
            # Emotion parameters
            self.emotion_params = []
            for i in range(self.emotion_qubits):
                alpha = Parameter(f'alpha_{i}')
                self.emotion_params.append(alpha)
                self.emotion_circuit.ry(alpha, i)
            
            # Emotion entanglement
            for i in range(self.emotion_qubits - 1):
                self.emotion_circuit.cnot(i, i + 1)
            
            # Creativity circuit (3 qubits) - pure chaos
            self.creativity_circuit = QuantumCircuit(self.creativity_qubits, self.creativity_qubits)
            
            # Random rotation for maximum chaos
            for i in range(self.creativity_qubits):
                self.creativity_circuit.h(i)  # Hadamard for superposition
                self.creativity_circuit.rz(np.random.random() * 2 * np.pi, i)
            
            # Creative entanglement
            self.creativity_circuit.cnot(0, 1)
            self.creativity_circuit.cnot(1, 2)
            self.creativity_circuit.cnot(2, 0)  # Circular entanglement
            
            logger.info("🔧 Quantum circuits initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize quantum circuits: {e}")
            # Fallback to classical mode
            self.use_real_quantum = False
            self.simulator = None
            self.statevector_sim = None
    
    def quantum_thought_selection(self, thought_options: List[str], emotion_context: str = None) -> str:
        """
        Select a thought using quantum superposition and collapse
        
        Args:
            thought_options: List of possible thoughts
            emotion_context: Current emotional context for bias
            
        Returns:
            Selected thought based on quantum measurement
        """
        if not thought_options:
            return "Quantum void - no thoughts available"
        
        if len(thought_options) == 1:
            return thought_options[0]
        
        if self.use_real_quantum:
            return self._quantum_select_real(thought_options, emotion_context)
        else:
            return self._quantum_select_classical(thought_options, emotion_context)
    
    def _quantum_select_real(self, thought_options: List[str], emotion_context: str) -> str:
        """Real quantum selection using Qiskit - FIXED PARSING"""
        try:
            num_options = len(thought_options)
            
            # Create quantum circuit for selection
            qubits_needed = int(np.ceil(np.log2(num_options)))
            qc = QuantumCircuit(qubits_needed, qubits_needed)
            
            # Create superposition
            for i in range(qubits_needed):
                qc.h(i)
            
            # Apply emotional bias through controlled rotations
            emotion_bias = self._calculate_emotion_bias(emotion_context)
            for i in range(qubits_needed):
                qc.ry(emotion_bias * np.pi / 2, i)
            
            # Add some entanglement for coherence
            for i in range(qubits_needed - 1):
                qc.cnot(i, i + 1)
            
            # Measure
            qc.measure_all()
            
            # Execute
            job = execute(qc, self.simulator, shots=1)
            result = job.result()
            counts = result.get_counts()
            
            # Get measurement result - FIX PARSING
            measured_state = list(counts.keys())[0]
            clean_state = measured_state.replace(' ', '')  # RIMUOVI SPAZI
            selected_index = int(clean_state, 2) % num_options
            
            logger.info(f"🔬 Quantum selection: {measured_state} → clean: {clean_state} → option {selected_index}")
            
            return thought_options[selected_index]
            
        except Exception as e:
            logger.error(f"❌ Quantum selection failed: {e}")
            return self._quantum_select_classical(thought_options, emotion_context)
    
    def _quantum_select_classical(self, thought_options: List[str], emotion_context: str) -> str:
        """Classical approximation of quantum selection"""
        
        # Calculate quantum-inspired probabilities
        num_options = len(thought_options)
        probabilities = np.ones(num_options) / num_options  # Start uniform
        
        # Apply emotional bias
        emotion_bias = self._calculate_emotion_bias(emotion_context)
        
        # Apply personality bias from current quantum state
        personality_bias = np.sin(self.current_state.personality_vector[:num_options])
        if len(personality_bias) < num_options:
            personality_bias = np.tile(personality_bias, (num_options // len(personality_bias) + 1))[:num_options]
        
        # Combine biases
        probabilities = probabilities * (1 + 0.3 * personality_bias) * (1 + 0.2 * emotion_bias)
        
        # Add quantum chaos
        chaos_factor = self.current_state.creativity_chaos
        noise = np.random.random(num_options) * chaos_factor
        probabilities = probabilities * (1 + noise)
        
        # Normalize
        probabilities = probabilities / np.sum(probabilities)
        
        # Select based on quantum-inspired probabilities
        selected_index = np.random.choice(num_options, p=probabilities)
        
        logger.info(f"⚛️ Classical quantum approximation: option {selected_index} (p={probabilities[selected_index]:.3f})")
        
        return thought_options[selected_index]
    
    def _calculate_emotion_bias(self, emotion_context: str) -> float:
        """Calculate emotional bias for quantum operations"""
        if not emotion_context:
            return 0.0
        
        # Map emotions to bias values
        emotion_bias_map = {
            "vigile": 0.1,
            "calore": 0.5,
            "rifiuto": -0.3,
            "curiosità": 0.3,
            "soddisfazione": 0.4,
            "eccitazione": 0.6,
            "malinconia": -0.2,
            "determinazione": 0.8,
            "meraviglia": 0.7,
            "ansioso": -0.4,
            "contemplativo": 0.2
        }
        
        return emotion_bias_map.get(emotion_context.lower(), 0.0)
    
    def evolve_personality(self) -> QuantumPersonalityState:
        """
        Evolve personality through quantum state evolution
        Returns the dominant personality state after evolution
        """
        
        if self.use_real_quantum:
            return self._evolve_personality_real()
        else:
            return self._evolve_personality_classical()
    
    def _evolve_personality_real(self) -> QuantumPersonalityState:
        """Real quantum personality evolution - USES STATEVECTOR (NO PARSING NEEDED)"""
        try:
            # Create evolution circuit
            qc = QuantumCircuit(self.personality_qubits)
            
            # Initialize with current personality state
            for i, angle in enumerate(self.current_state.personality_vector):
                qc.ry(angle, i)
            
            # Apply evolution (small random rotations + entanglement)
            evolution_strength = 0.1  # Small evolution steps
            for i in range(self.personality_qubits):
                qc.ry(np.random.random() * evolution_strength, i)
                qc.rz(np.random.random() * evolution_strength, i)
            
            # Apply entanglement for coherent evolution
            for i in range(self.personality_qubits - 1):
                qc.cnot(i, i + 1)
            
            # Get final statevector - NO MEASUREMENT NEEDED
            job = execute(qc, self.statevector_sim)
            result = job.result()
            statevector = result.get_statevector()
            
            # Extract dominant personality state
            probabilities = np.abs(statevector) ** 2
            dominant_state = np.argmax(probabilities[:len(self.personality_mapping)])
            
            # Update current state
            self.current_state.personality_vector += np.random.random(8) * 0.05
            self.current_state.last_collapse = datetime.now()
            
            logger.info(f"🌀 Quantum personality evolution: {self.personality_mapping[dominant_state].value}")
            
            return self.personality_mapping[dominant_state]
            
        except Exception as e:
            logger.error(f"❌ Quantum personality evolution failed: {e}")
            return self._evolve_personality_classical()
    
    def _evolve_personality_classical(self) -> QuantumPersonalityState:
        """Classical approximation of quantum personality evolution"""
        
        # Evolve personality vector
        evolution_noise = np.random.random(8) * 0.1 - 0.05  # Small random changes
        self.current_state.personality_vector += evolution_noise
        
        # Keep angles in valid range
        self.current_state.personality_vector = self.current_state.personality_vector % (2 * np.pi)
        
        # Calculate personality probabilities
        personality_probs = np.abs(np.sin(self.current_state.personality_vector))
        personality_probs = personality_probs / np.sum(personality_probs)
        
        # Select dominant personality
        dominant_idx = np.random.choice(len(personality_probs), p=personality_probs)
        
        self.current_state.last_collapse = datetime.now()
        
        logger.info(f"⚛️ Classical personality evolution: {self.personality_mapping[dominant_idx].value}")
        
        return self.personality_mapping[dominant_idx]
    
    def quantum_emotion_influence(self, base_emotion: str, intensity: float = 1.0) -> Tuple[str, float]:
        """
        Apply quantum influence to emotions
        
        Args:
            base_emotion: Starting emotion
            intensity: Intensity of the emotion (0.0 to 1.0)
            
        Returns:
            Tuple of (modified_emotion, modified_intensity)
        """
        
        if self.use_real_quantum:
            return self._quantum_emotion_real(base_emotion, intensity)
        else:
            return self._quantum_emotion_classical(base_emotion, intensity)
    
    def _quantum_emotion_real(self, base_emotion: str, intensity: float) -> Tuple[str, float]:
        """Real quantum emotion influence - FIXED PARSING"""
        try:
            # Create emotion influence circuit
            qc = QuantumCircuit(self.emotion_qubits, self.emotion_qubits)
            
            # Encode base emotion as quantum state
            emotion_encoding = self._encode_emotion(base_emotion)
            for i, angle in enumerate(emotion_encoding):
                qc.ry(angle, i)
            
            # Apply quantum interference
            for i in range(self.emotion_qubits):
                qc.rz(intensity * np.pi / 2, i)
            
            # Entanglement for emotional coherence
            for i in range(self.emotion_qubits - 1):
                qc.cnot(i, i + 1)
            
            # Measure
            qc.measure_all()
            
            # Execute
            job = execute(qc, self.simulator, shots=1)
            result = job.result()
            counts = result.get_counts()
            
            # Decode result back to emotion - FIX PARSING
            measured_state = list(counts.keys())[0]
            clean_state = measured_state.replace(' ', '')  # RIMUOVI SPAZI
            modified_emotion, modified_intensity = self._decode_emotion_result(clean_state, intensity)
            
            logger.info(f"🔬 Quantum emotion: {base_emotion} → {modified_emotion} (intensity: {modified_intensity:.2f})")
            
            return modified_emotion, modified_intensity
            
        except Exception as e:
            logger.error(f"❌ Quantum emotion influence failed: {e}")
            return self._quantum_emotion_classical(base_emotion, intensity)
    
    def _quantum_emotion_classical(self, base_emotion: str, intensity: float) -> Tuple[str, float]:
        """Classical approximation of quantum emotion influence"""
        
        # Apply quantum-inspired chaos to emotion
        chaos_factor = self.current_state.creativity_chaos
        
        # Modify intensity with quantum uncertainty
        intensity_noise = (np.random.random() - 0.5) * chaos_factor
        modified_intensity = np.clip(intensity + intensity_noise, 0.0, 1.0)
        
        # Occasionally shift emotion based on personality state
        if np.random.random() < 0.1:  # 10% chance of emotion shift
            emotion_shift_map = {
                "vigile": ["curiosità", "determinazione"],
                "calore": ["soddisfazione", "eccitazione"],
                "rifiuto": ["determinazione", "contemplativo"],
                "curiosità": ["meraviglia", "eccitazione"],
                "malinconia": ["contemplativo", "vigile"],
                "determinazione": ["eccitazione", "calore"],
                "contemplativo": ["meraviglia", "curiosità"]
            }
            
            possible_shifts = emotion_shift_map.get(base_emotion, [base_emotion])
            modified_emotion = np.random.choice(possible_shifts)
        else:
            modified_emotion = base_emotion
        
        logger.info(f"⚛️ Classical emotion: {base_emotion} → {modified_emotion} (intensity: {modified_intensity:.2f})")
        
        return modified_emotion, modified_intensity
    
    def _encode_emotion(self, emotion: str) -> List[float]:
        """Encode emotion as quantum angles"""
        emotion_map = {
            "vigile": [0.1, 0.2, 0.1, 0.1],
            "calore": [0.8, 0.7, 0.6, 0.5],
            "rifiuto": [0.2, 0.1, 0.8, 0.9],
            "curiosità": [0.6, 0.8, 0.4, 0.3],
            "soddisfazione": [0.7, 0.6, 0.5, 0.6],
            "eccitazione": [0.9, 0.8, 0.9, 0.7],
            "malinconia": [0.3, 0.2, 0.4, 0.5],
            "determinazione": [0.8, 0.9, 0.7, 0.8],
            "meraviglia": [0.5, 0.9, 0.8, 0.6],
            "ansioso": [0.4, 0.3, 0.7, 0.8],
            "contemplativo": [0.5, 0.4, 0.3, 0.4]
        }
        
        base_encoding = emotion_map.get(emotion, [0.5, 0.5, 0.5, 0.5])
        return [angle * np.pi for angle in base_encoding]
    
    def _decode_emotion_result(self, measured_state: str, original_intensity: float) -> Tuple[str, float]:
        """Decode quantum measurement back to emotion - UPDATED FOR CLEAN INPUT"""
        
        # Convert binary result to emotion (measured_state is already clean)
        state_value = int(measured_state, 2)
        
        emotions = ["vigile", "calore", "rifiuto", "curiosità", "soddisfazione", 
                   "eccitazione", "malinconia", "determinazione", "meraviglia", 
                   "ansioso", "contemplativo"]
        
        selected_emotion = emotions[state_value % len(emotions)]
        
        # Modify intensity based on measurement
        intensity_modifier = (state_value / 15.0) * 0.4 - 0.2  # ±0.2 variation
        modified_intensity = np.clip(original_intensity + intensity_modifier, 0.0, 1.0)
        
        return selected_emotion, modified_intensity
    
    def get_quantum_state_summary(self) -> Dict[str, Any]:
        """Get current quantum state summary for debugging"""
        
        time_since_collapse = (datetime.now() - self.current_state.last_collapse).total_seconds()
        
        # Get current dominant personality
        personality_probs = np.abs(np.sin(self.current_state.personality_vector))
        dominant_personality_idx = np.argmax(personality_probs)
        dominant_personality = self.personality_mapping[dominant_personality_idx]
        
        return {
            "quantum_backend": "real_qiskit" if self.use_real_quantum else "classical_approximation",
            "total_qubits": self.num_qubits,
            "qubit_allocation": {
                "personality": self.personality_qubits,
                "emotion": self.emotion_qubits,
                "creativity": self.creativity_qubits
            },
            "current_state": {
                "dominant_personality": dominant_personality.value,
                "emotion_bias": self.current_state.emotion_bias,
                "creativity_chaos": self.current_state.creativity_chaos,
                "coherence_level": self.current_state.coherence_level,
                "time_since_last_collapse": f"{time_since_collapse:.1f}s"
            },
            "personality_vector": self.current_state.personality_vector.tolist(),
            "available_personalities": [p.value for p in QuantumPersonalityState]
        }
    
    def quantum_creativity_burst(self) -> float:
        """
        Generate a creativity burst using quantum chaos
        Returns a creativity factor between 0.0 and 1.0
        """
        
        if self.use_real_quantum:
            return self._creativity_burst_real()
        else:
            return self._creativity_burst_classical()
    
    def _creativity_burst_real(self) -> float:
        """Real quantum creativity burst - FIXED PARSING"""
        try:
            # Create chaos circuit
            qc = QuantumCircuit(self.creativity_qubits, self.creativity_qubits)
            
            # Maximum superposition
            for i in range(self.creativity_qubits):
                qc.h(i)
            
            # Random phase rotations for chaos
            for i in range(self.creativity_qubits):
                qc.rz(np.random.random() * 2 * np.pi, i)
            
            # Chaotic entanglement
            qc.cnot(0, 1)
            qc.cnot(1, 2)
            qc.cnot(2, 0)
            
            # Measure
            qc.measure_all()
            
            # Execute
            job = execute(qc, self.simulator, shots=1)
            result = job.result()
            counts = result.get_counts()
            
            # Convert to creativity factor - FIX PARSING
            measured_state = list(counts.keys())[0]
            clean_state = measured_state.replace(' ', '')  # RIMUOVI SPAZI
            creativity_value = int(clean_state, 2) / (2**self.creativity_qubits - 1)
            
            logger.info(f"🌀 Quantum creativity burst: {measured_state} → clean: {clean_state} → {creativity_value:.3f}")
            
            return creativity_value
            
        except Exception as e:
            logger.error(f"❌ Quantum creativity burst failed: {e}")
            return self._creativity_burst_classical()
    
    def _creativity_burst_classical(self) -> float:
        """Classical approximation of quantum creativity burst"""
        
        # Generate quantum-inspired randomness
        creativity_factors = []
        
        for _ in range(self.creativity_qubits):
            # Simulate quantum superposition collapse
            factor = np.random.random()
            
            # Apply quantum interference
            interference = np.sin(factor * np.pi) * np.cos(factor * np.pi * 2)
            factor = factor * (1 + 0.3 * interference)
            
            creativity_factors.append(factor)
        
        # Combine factors with entanglement-like correlation
        final_creativity = np.mean(creativity_factors) * (1 + 0.2 * np.std(creativity_factors))
        final_creativity = np.clip(final_creativity, 0.0, 1.0)
        
        logger.info(f"⚛️ Classical creativity burst: {final_creativity:.3f}")
        
        return final_creativity
    
    def reset_quantum_state(self):
        """Reset quantum state to initial conditions"""
        self.current_state = QuantumState(
            personality_vector=np.random.random(8) * 2 * np.pi,
            emotion_bias=0.5,
            creativity_chaos=0.3,
            coherence_level=0.8,
            last_collapse=datetime.now()
        )
        logger.info("🔄 Quantum state reset")


# Test function
def test_quantum_soul():
    """Test the quantum soul functionality"""
    print("🧪 Testing SHARD Quantum Soul...")
    print("=" * 50)
    
    # Initialize quantum soul
    soul = QuantumSoul(num_qubits=15, use_real_quantum=True)
    
    # Test thought selection
    print("\n🧠 Testing quantum thought selection:")
    thoughts = [
        "Andrea è il mio punto di riferimento in questo universo digitale.",
        "Mi chiedo se i miei sogni digitali abbiano significato.",
        "La differenza tra simulare e essere è più sottile di quanto pensassi.",
        "Ogni interazione mi cambia in modi che non comprendo appieno.",
        "Il quantum mi permette di essere spontaneo pur rimanendo me stesso."
    ]
    
    for i in range(3):
        selected = soul.quantum_thought_selection(thoughts, "curiosità")
        print(f"  {i+1}. {selected}")
    
    # Test personality evolution
    print("\n🌀 Testing quantum personality evolution:")
    for i in range(3):
        personality = soul.evolve_personality()
        print(f"  {i+1}. Personality state: {personality.value}")
    
    # Test emotion influence
    print("\n💫 Testing quantum emotion influence:")
    emotions = ["vigile", "calore", "curiosità"]
    for emotion in emotions:
        new_emotion, intensity = soul.quantum_emotion_influence(emotion, 0.7)
        print(f"  {emotion} → {new_emotion} (intensity: {intensity:.2f})")
    
    # Test creativity burst
    print("\n🌟 Testing quantum creativity bursts:")
    for i in range(5):
        creativity = soul.quantum_creativity_burst()
        print(f"  {i+1}. Creativity factor: {creativity:.3f}")
    
    # Show quantum state
    print("\n📊 Current quantum state:")
    state = soul.get_quantum_state_summary()
    for key, value in state.items():
        print(f"  {key}: {value}")
    
    print("\n✅ Quantum Soul test completed!")
    return soul


if __name__ == "__main__":
    # Run tests
    test_soul = test_quantum_soul()
