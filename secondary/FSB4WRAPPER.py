#!/usr/bin/env python3
"""
FSB4 Speech Synthesizer - Full Debug GUI
ENFORCED WORKFLOW:
  1. Edit spec → Parse to phonemes (internal representation)
  2. Spec → Save Bytecode (.phx) = FILE I/O ONLY (NO AUDIO)
  3. RENDER AUDIO = OPEN FILE SELECTOR → LOAD .phx → SYNTHESIZE → CACHE BUFFER
  4. PLAY = CACHED BUFFER ONLY (ZERO synthesis during playback)
"""
import sys
import os
import threading
import time
import numpy as np
import wave
import subprocess
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import re

# Import FSB4 core functionality
try:
    import FSB4 as fsb
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    import FSB4 as fsb

class FSB4DebugGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("FSB4 Debug Synthesizer")
        self.root.geometry("800x600")
        
        # STATE ENFORCEMENT (critical for architecture)
        self.current_specs = []          # Internal phoneme specs (parsed representation)
        self.rendered_audio = None       # Cached WAV buffer AFTER rendering from bytecode
        self.is_playing = False
        self.playback_thread = None
        
        # Build UI with full categories/tabs
        self.setup_ui()
        self.load_voices()
        self.update_ui_state()
        
    def setup_ui(self):
        # MAIN NOTEBOOK FOR CATEGORIES
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # ════════════════════════════════════════════════════════════════════════════════
        # TAB 1: PHONEME EDITOR (Full spec editing workflow)
        # ════════════════════════════════════════════════════════════════════════════════
        editor_frame = ttk.Frame(self.notebook)
        self.notebook.add(editor_frame, text="Phoneme Editor")
        
        # Split pane: phoneme library | spec editor
        paned = ttk.PanedWindow(editor_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left: Phoneme library browser
        lib_frame = ttk.LabelFrame(paned, text="Phoneme Library (double-click to insert)")
        paned.add(lib_frame)
        
        self.phoneme_list = tk.Listbox(lib_frame, width=25, height=20, font=("Courier", 10))
        self.phoneme_list.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.phoneme_list.bind('<Double-1>', self.add_phoneme_to_editor)
        
        # Populate library with all phonemes
        for byte_val in sorted(fsb.BYTE_TO_PHONEME.keys()):
            ph = fsb.BYTE_TO_PHONEME[byte_val]
            self.phoneme_list.insert(tk.END, f"0x{byte_val:02X} {ph}")
        
        # Right: Spec editor panel
        editor_panel = ttk.Frame(paned)
        paned.add(editor_panel)
        
        ttk.Label(editor_panel, text="Phoneme Spec (PHONEME DURATION P0 [P1...]):").pack(anchor=tk.W, padx=5, pady=(5,0))
        self.spec_editor = scrolledtext.ScrolledText(editor_panel, width=60, height=15, font=("Courier", 10))
        self.spec_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Editor action buttons
        btn_frame = ttk.Frame(editor_panel)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(btn_frame, text="Load Spec", command=self.load_phoneme_spec).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Save Spec", command=self.save_phoneme_spec).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Clear", command=lambda: self.spec_editor.delete('1.0', tk.END)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Parse to Phonemes", command=self.parse_spec_to_phonemes).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="→ Save Bytecode (.phx)", command=self.save_bytecode).pack(side=tk.LEFT, padx=2)
        
        # ════════════════════════════════════════════════════════════════════════════════
        # TAB 2: VOICE CONTROLS (Voice selection + parameters + file ops)
        # ════════════════════════════════════════════════════════════════════════════════
        voice_frame = ttk.Frame(self.notebook)
        self.notebook.add(voice_frame, text="Voice Controls")
        
        # Voice selection section
        voice_sel_frame = ttk.LabelFrame(voice_frame, text="Voice Selection")
        voice_sel_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(voice_sel_frame, text="Active Voice:").pack(side=tk.LEFT, padx=5)
        self.voice_combo = ttk.Combobox(voice_sel_frame, state="readonly", width=30)
        self.voice_combo.pack(side=tk.LEFT, padx=5)
        self.voice_combo.bind('<<ComboboxSelected>>', self.change_voice)
        
        ttk.Label(voice_sel_frame, text="Pitch Base:").pack(side=tk.LEFT, padx=15)
        self.pitch_spin = ttk.Spinbox(voice_sel_frame, from_=50, to=400, width=6)
        self.pitch_spin.set(115)
        self.pitch_spin.pack(side=tk.LEFT, padx=5)
        ttk.Label(voice_sel_frame, text="Hz").pack(side=tk.LEFT, padx=2)
        
        # Synthesis parameters
        param_frame = ttk.LabelFrame(voice_frame, text="Synthesis Parameters")
        param_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Speed control
        ttk.Label(param_frame, text="Speed (%):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.speed_var = tk.IntVar(value=100)
        ttk.Scale(param_frame, from_=50, to=200, variable=self.speed_var, orient=tk.HORIZONTAL).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        ttk.Label(param_frame, textvariable=self.speed_var).grid(row=0, column=2, padx=5)
        
        # Formant shift
        ttk.Label(param_frame, text="Formant Shift (Hz):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.formant_shift_var = tk.IntVar(value=0)
        ttk.Scale(param_frame, from_=-200, to=200, variable=self.formant_shift_var, orient=tk.HORIZONTAL).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=5)
        ttk.Label(param_frame, textvariable=self.formant_shift_var).grid(row=1, column=2, padx=5)
        
        param_frame.columnconfigure(1, weight=1)
        
        # File operations (bytecode-focused)
        file_frame = ttk.LabelFrame(voice_frame, text="Bytecode File Operations")
        file_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(file_frame, text="Load .PHX Bytecode", command=self.load_bytecode).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(file_frame, text="Save .PHX Bytecode", command=self.save_bytecode).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(file_frame, text="Load .PHN (Legacy)", command=self.load_phn_file).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(file_frame, text="Export Rendered WAV", command=self.export_wav).pack(side=tk.LEFT, padx=5, pady=5)
        
        # ════════════════════════════════════════════════════════════════════════════════
        # TAB 3: AUDIO RENDERING (Dedicated tab for bytecode → audio workflow)
        # ════════════════════════════════════════════════════════════════════════════════
        render_frame = ttk.Frame(self.notebook)
        self.notebook.add(render_frame, text="Audio Rendering")
        
        render_instr = ttk.LabelFrame(render_frame, text="Render Audio from Bytecode")
        render_instr.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        instr_text = tk.Text(render_instr, wrap=tk.WORD, font=("Arial", 10), height=8, bg="#f0f0f0")
        instr_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        instr_text.insert(tk.END, "RENDER WORKFLOW:\n\n"
                          "1. Click 'Render Audio from .phx File' below\n"
                          "2. SELECT a valid .phx bytecode file in the file dialog\n"
                          "3. FSB4 will LOAD the bytecode → SYNTHESIZE audio → CACHE buffer\n"
                          "4. Use playback controls to hear the cached audio (ZERO synthesis overhead)\n\n"
                          "⚠️  AUDIO SYNTHESIS ONLY OCCURS AFTER VALID BYTECODE IS LOADED")
        instr_text.config(state=tk.DISABLED)
        
        render_btn_frame = ttk.Frame(render_frame)
        render_btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(render_btn_frame, text="Render Audio from .phx File", 
                  command=self.render_audio_from_file_selector, width=30).pack(pady=10)
        
        # ════════════════════════════════════════════════════════════════════════════════
        # TAB 4: REFERENCE (Phoneme guide + technical specs)
        # ════════════════════════════════════════════════════════════════════════════════
        ref_frame = ttk.Frame(self.notebook)
        self.notebook.add(ref_frame, text="Reference")
        
        ref_text = tk.Text(ref_frame, wrap=tk.WORD, font=("Courier", 9), bg="white")
        ref_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ref_content = """
PHONEME REFERENCE GUIDE
═══════════════════════════════════════════════════════════════════════════════

VOWELS:      AH AE AA AO EH EY IH IY OW UH UW ER
STOPS:       P T K B D G CH (unvoiced/voiced pairs)
FRICATIVES:  F S SH TH (unvoiced)  V Z ZH DH (voiced)
NASALS:      M N NG
LIQUIDS:     L R
GLIDES:      W Y HH JH

EXAMPLE WORDS:
  hello    → HH EH L OW
  world    → W ER L D
  test     → T EH S T
  robot    → R OW B AH T
  formant  → F AO R M AH N T

SPECIAL NOTES:
  • SIL = silence (0.19s default)
  • _FINAL suffix increases vowel duration by 40%
  • Pitch contours: space-separated Hz values (max 8 points)
  • Duration range: 0.01s - 2.0s per phoneme

TECHNICAL SPECS:
  • Sample rate: 48 kHz
  • Format: .PHX (50 bytes/phoneme) - parameterized bytecode
  • Legacy: .PHN (1 byte/phoneme) - simple phoneme stream
  • Formant synthesis with glottal pulse modeling
  • Real-time pitch contour interpolation

FSB4 ARCHITECTURE ENFORCEMENT:
  ✓ Spec → Parse → Internal specs (NO audio)
  ✓ Specs → Save Bytecode (.phx) = FILE I/O ONLY (NO audio)
  ✓ Render Audio = FILE SELECTOR → LOAD .phx → SYNTHESIZE → CACHE BUFFER
  ✓ Play = CACHED BUFFER ONLY (ZERO synthesis during playback)

DEBUG WORKFLOW:
  1. Edit spec in Phoneme Editor tab
  2. Click "Parse to Phonemes" to validate
  3. Click "→ Save Bytecode (.phx)" to generate VALID bytecode
  4. Go to "Audio Rendering" tab → Click "	Render Audio from .phx File"
  5. SELECT .phx file → Audio synthesized and cached
  6. Use playback controls to hear cached audio (NO synthesis overhead)

EXAMPLE PHONEME INPUT:
    SIL 0.190 0.0
    HH  0.190 155
    EH  0.100 155
    L   0.100 155
    OW  0.190 155
    SIL 0.280 0.0
"""
        ref_text.insert(tk.END, ref_content)
        ref_text.config(state=tk.DISABLED)
        
        # ════════════════════════════════════════════════════════════════════════════════
        # GLOBAL PLAYBACK CONTROLS (bottom of window)
        # ════════════════════════════════════════════════════════════════════════════════
        play_frame = ttk.LabelFrame(self.root, text="Playback Controls (cached audio ONLY - NO SYNTHESIS)")
        play_frame.pack(fill=tk.X, padx=10, pady=(0,5))
        
        self.play_btn = ttk.Button(play_frame, text="▶ Play Cached Audio", command=self.play_cached_audio, width=20)
        self.play_btn.pack(side=tk.LEFT, padx=10, pady=5)
        
        self.stop_btn = ttk.Button(play_frame, text="■ Stop", command=self.stop_playback, width=10, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=10, pady=5)
        
        # Status bar
        self.status_var = tk.StringVar(value="Workflow: Parse → Save Bytecode → Render from .phx File → Play Cached Buffer")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    # ════════════════════════════════════════════════════════════════════════════════
    # VOICE MANAGEMENT
    # ════════════════════════════════════════════════════════════════════════════════
    def load_voices(self):
        voices = list(fsb.VOICE_REGISTRY.list_voices().keys())
        self.voice_combo['values'] = voices
        if 'Default' in voices:
            self.voice_combo.set('Default')
            fsb.VOICE_REGISTRY.set_current_voice('Default')
    
    def change_voice(self, event=None):
        name = self.voice_combo.get()
        if fsb.VOICE_REGISTRY.set_current_voice(name):
            self.status_var.set(f"Voice changed to: {name}")
            self.rendered_audio = None
            self.update_ui_state()
    
    # ════════════════════════════════════════════════════════════════════════════════
    # PHONEME EDITOR OPERATIONS
    # ════════════════════════════════════════════════════════════════════════════════
    def add_phoneme_to_editor(self, event=None):
        selection = self.phoneme_list.curselection()
        if not selection:
            return
        item = self.phoneme_list.get(selection[0])
        phoneme = item.split()[1]  # Extract "PH" from "0xXX PH"
        default_dur = "0.14" if phoneme in fsb.VOWELS else "0.12"
        default_pitch = "115.0"
        current = self.spec_editor.get('1.0', tk.END).strip()
        if current:
            self.spec_editor.insert(tk.END, f"\n{phoneme} {default_dur} {default_pitch}")
        else:
            self.spec_editor.insert(tk.END, f"{phoneme} {default_dur} {default_pitch}")
        self.rendered_audio = None
        self.update_ui_state()
    
    def parse_spec_to_phonemes(self):
        text = self.spec_editor.get('1.0', tk.END).strip()
        if not text:
            self.status_var.set("ERROR: No spec data!")
            return
        
        try:
            # Auto-detect English text vs phoneme spec
            if not re.search(r'\d+\.\d+', text):
                # Treat as English text
                phonemes = fsb.text_to_phonemes(text)
                pitch = float(self.pitch_spin.get())
                specs = fsb.phonemes_to_spec(phonemes, fsb.VOICE_REGISTRY.current_voice, pitch_base=pitch)
            else:
                # Parse as phoneme spec
                specs = fsb.parse_phoneme_spec(text, fsb.VOICE_REGISTRY.current_voice)
            
            if not specs or len(specs) <= 2:
                self.status_var.set("ERROR: No valid phonemes generated!")
                return
            
            self.current_specs = specs
            
            # Update editor with normalized readable format
            self.spec_editor.delete('1.0', tk.END)
            self.spec_editor.insert(tk.END, fsb.specs_to_readable(specs))
            
            total_dur = sum(s['duration'] for s in specs)
            self.status_var.set(f"✓ Parsed {len(specs)-2} phonemes ({total_dur:.2f}s total). Save as .phx bytecode to render audio.")
        except Exception as e:
            self.status_var.set(f"ERROR parsing: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def update_ui_state(self):
        """Update UI controls based on current state"""
        # Play button enabled ONLY with rendered audio AND not playing
        play_state = tk.NORMAL if (self.rendered_audio is not None and not self.is_playing) else tk.DISABLED
        
        self.play_btn.config(state=play_state)
        self.stop_btn.config(state=tk.NORMAL if self.is_playing else tk.DISABLED)
    
    # ════════════════════════════════════════════════════════════════════════════════
    # BYTECODE OPERATIONS (FILE I/O ONLY - NO AUDIO SYNTHESIS)
    # ════════════════════════════════════════════════════════════════════════════════
    def save_bytecode(self):
        """SAVE BYTECODE ONLY - ZERO AUDIO SYNTHESIS"""
        if not self.current_specs:
            messagebox.showerror("Error", "Parse spec to phonemes first!")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".phx",
            filetypes=[("PHX Files", "*.phx"), ("All Files", "*.*")]
        )
        if not filename:
            return
        
        try:
            # CRITICAL: This ONLY writes bytecode to disk - NO audio generation
            fsb.save_parameterized_phonemes(filename, self.current_specs)
            
            self.status_var.set(f"✓ Bytecode SAVED to: {filename} (FILE I/O ONLY - NO AUDIO GENERATED)")
        except Exception as e:
            self.status_var.set(f"ERROR saving PHX: {str(e)}")
            messagebox.showerror("Save Error", f"Failed to save PHX file:\n{str(e)}")
    
    def load_bytecode(self):
        """LOAD BYTECODE ONLY - ZERO AUDIO SYNTHESIS"""
        filename = filedialog.askopenfilename(
            filetypes=[("PHX Files", "*.phx"), ("All Files", "*.*")]
        )
        if not filename:
            return
        
        try:
            # CRITICAL: This ONLY reads bytecode from disk - NO audio generation
            specs = fsb.load_parameterized_phonemes(filename)
            
            self.current_specs = specs
            
            # Update editor with loaded specs
            self.spec_editor.delete('1.0', tk.END)
            self.spec_editor.insert(tk.END, fsb.specs_to_readable(specs))
            
            total_dur = sum(s['duration'] for s in specs)
            self.status_var.set(f"✓ Bytecode LOADED from: {filename} ({len(specs)} phonemes, {total_dur:.2f}s) - FILE I/O ONLY (NO AUDIO)")
        except Exception as e:
            self.status_var.set(f"ERROR loading PHX: {str(e)}")
            messagebox.showerror("Load Error", f"Failed to load PHX file:\n{str(e)}")
    
    # ════════════════════════════════════════════════════════════════════════════════
    # AUDIO RENDERING (BYTECODE FILE SELECTOR → SYNTHESIS → CACHE)
    # ════════════════════════════════════════════════════════════════════════════════
    def render_audio_from_file_selector(self):
        """OPEN FILE SELECTOR → LOAD .phx → SYNTHESIZE AUDIO → CACHE BUFFER"""
        # STEP 1: Open file selector for .phx bytecode
        filename = filedialog.askopenfilename(
            title="Select .phx Bytecode File to Render",
            filetypes=[("PHX Files", "*.phx"), ("All Files", "*.*")]
        )
        if not filename:
            self.status_var.set("Render cancelled - no file selected")
            return
        
        # STEP 2: Load bytecode from selected file
        try:
            self.status_var.set(f".Loading bytecode from: {filename}")
            self.root.update_idletasks()
            
            specs = fsb.load_parameterized_phonemes(filename)
            self.current_specs = specs
            
            self.status_var.set(f".Synthesizing audio from bytecode...")
            self.root.update_idletasks()
            
            # STEP 3: SYNTHESIZE AUDIO FROM BYTECODE (THIS IS THE ONLY SYNTHESIS POINT)
            synth = fsb.FormantSynthesizer(fsb.VOICE_REGISTRY.current_voice, sample_rate=fsb.smp)
            audio_buffer = synth.synthesize_from_specs(specs)  # ← CORE SYNTHESIS FROM BYTECODE
            
            # Apply speed adjustment
            speed_factor = self.speed_var.get() / 100.0
            if speed_factor != 1.0:
                original_length = len(audio_buffer)
                new_length = int(original_length / speed_factor)
                x_old = np.linspace(0, 1, original_length)
                x_new = np.linspace(0, 1, new_length)
                audio_buffer = np.interp(x_new, x_old, audio_buffer)
            
            # STEP 4: Cache the rendered audio
            self.rendered_audio = audio_buffer
            
            duration = len(self.rendered_audio) / fsb.smp
            self.status_var.set(f"✓ Audio RENDERED from {filename} ({duration:.2f}s). Click PLAY to hear cached buffer.")
            self.update_ui_state()
            
        except Exception as e:
            self.rendered_audio = None
            self.status_var.set(f"Render error: {str(e)}")
            messagebox.showerror("Render Error", f"Failed to render audio from bytecode:\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    # ════════════════════════════════════════════════════════════════════════════════
    # PLAYBACK (CACHED BUFFER ONLY - ZERO SYNTHESIS)
    # ════════════════════════════════════════════════════════════════════════════════
    def play_cached_audio(self):
        """PLAY CACHED BUFFER ONLY - ABSOLUTELY ZERO SYNTHESIS"""
        if self.rendered_audio is None:
            messagebox.showerror(
                "No Rendered Audio", 
                "Render audio first using '	Render Audio from .phx File' button!\n\n"
                "Workflow:\n"
                "1. Save or obtain a valid .phx bytecode file\n"
                "2. Click '	Render Audio from .phx File' in Audio Rendering tab\n"
                "3. SELECT the .phx file in the file dialog\n"
                "4. THEN click PLAY"
            )
            self.status_var.set("ERROR: Render audio before playback")
            return
        
        if self.is_playing:
            self.stop_playback()
        
        # Setup playback state
        self.is_playing = True
        self.play_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.status_var.set("Playing CACHED audio buffer (ZERO synthesis overhead)...")
        
        # Start playback in background thread
        self.playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self.playback_thread.start()
    
    def _playback_worker(self):
        """Worker thread for audio playback (NO SYNTHESIS)"""
        try:
            # Write cached buffer to temp WAV
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp:
                tmp_path = tmp.name
            
            audio_clipped = np.clip(self.rendered_audio * 32767, -32768, 32767).astype(np.int16)
            with wave.open(tmp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(fsb.smp)
                wf.writeframes(audio_clipped.tobytes())
            
            # Play temp file
            if sys.platform == 'win32':
                import winsound
                winsound.PlaySound(tmp_path, winsound.SND_FILENAME)
            else:
                player = 'aplay' if sys.platform.startswith('linux') else 'afplay'
                subprocess.run([player, tmp_path], 
                             stdout=subprocess.DEVNULL, 
                             stderr=subprocess.DEVNULL)
            
            # Cleanup
            time.sleep(0.5)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            
            # Update UI on main thread
            self.root.after(0, self._playback_finished)
        except Exception as e:
            self.root.after(0, lambda: self.status_var.set(f"Playback error: {str(e)}"))
            self.root.after(0, self._playback_finished)
            import traceback
            traceback.print_exc()
    
    def _playback_finished(self):
        self.is_playing = False
        self.update_ui_state()
        self.status_var.set("Playback complete (cached buffer only)")
    
    def stop_playback(self):
        """Stop playback WITHOUT synthesis"""
        if sys.platform == 'win32':
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except:
                pass
        self.is_playing = False
        self.update_ui_state()
        self.status_var.set("Playback stopped")
    
    # ════════════════════════════════════════════════════════════════════════════════
    # FILE OPERATIONS (Spec I/O + Legacy PHN)
    # ════════════════════════════════════════════════════════════════════════════════
    def load_phoneme_spec(self):
        filename = filedialog.askopenfilename(
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.spec_editor.delete('1.0', tk.END)
                    self.spec_editor.insert(tk.END, f.read())
                self.rendered_audio = None
                self.update_ui_state()
                self.status_var.set(f"Loaded spec from: {filename}")
            except Exception as e:
                self.status_var.set(f"ERROR loading file: {str(e)}")
    
    def save_phoneme_spec(self):
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.spec_editor.get('1.0', tk.END))
                self.status_var.set(f"Saved spec to: {filename}")
            except Exception as e:
                self.status_var.set(f"ERROR saving file: {str(e)}")
    
    def load_phn_file(self):
        """Load legacy .phn format (1 byte/phoneme)"""
        filename = filedialog.askopenfilename(
            filetypes=[("PHN Files", "*.phn"), ("All Files", "*.*")]
        )
        if not filename:
            return
        
        try:
            with open(filename, 'rb') as f:
                content = f.read()
            
            # Handle optional header with voice name
            if content.startswith(b'\xFE\xEB\xDA\xED') and len(content) > 5:
                name_len = content[4]
                try:
                    voice_name = content[5:5+name_len].decode('utf-8')
                    byte_data = content[5+name_len:]
                    if fsb.VOICE_REGISTRY.set_current_voice(voice_name):
                        self.voice_combo.set(voice_name)
                except:
                    byte_data = content[5:]
            else:
                byte_data = content
            
            # Convert bytes to phonemes
            phonemes = []
            for byte_val in byte_data:
                if byte_val in fsb.BYTE_TO_PHONEME:
                    phonemes.append(fsb.BYTE_TO_PHONEME[byte_val])
            
            if not phonemes:
                self.status_var.set("ERROR: No valid phonemes in PHN file!")
                return
            
            # Convert to specs using current voice
            specs = []
            for ph in phonemes:
                ph_data = fsb.VOICE_REGISTRY.current_voice.get_phoneme_data(ph)
                duration = ph_data.get('length', 0.14)
                pitch = 115.0 if ph_data.get('voiced', False) and ph != 'SIL' else 0.0
                f1 = ph_data.get('f1', 0.0) or 0.0
                f2 = ph_data.get('f2', 0.0) or 0.0
                f3 = ph_data.get('f3', 0.0) or 0.0
                specs.append({
                    'phoneme': ph,
                    'duration': duration,
                    'pitch_contour': [pitch],
                    'num_pitch_points': 1,
                    'f1': f1,
                    'f2': f2,
                    'f3': f3,
                    'voiced': ph not in {'SIL','B','D','G','P','T','K','F','S','SH','TH','HH','CH'}
                })
            
            self.current_specs = specs
            self.rendered_audio = None
            self.update_ui_state()
            
            self.spec_editor.delete('1.0', tk.END)
            self.spec_editor.insert(tk.END, fsb.specs_to_readable(specs))
            self.status_var.set(f"Loaded {len(phonemes)} legacy phonemes from {filename} (NOT valid .phx bytecode)")
        except Exception as e:
            self.status_var.set(f"ERROR loading PHN: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def export_wav(self):
        """Export rendered audio buffer to WAV file"""
        if self.rendered_audio is None:
            messagebox.showerror("Render First", "Render audio before exporting WAV!")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV Files", "*.wav"), ("All Files", "*.*")]
        )
        if not filename:
            return
        
        try:
            if not filename.endswith('.wav'):
                filename += '.wav'
            fsb.save_wav(filename, self.rendered_audio, fsb.smp)
            
            size_kb = os.path.getsize(filename) / 1024
            duration = len(self.rendered_audio) / fsb.smp
            self.status_var.set(f"✓ WAV exported: {filename} ({size_kb:.1f} KB, {duration:.2f}s)")
        except Exception as e:
            self.status_var.set(f"ERROR exporting WAV: {str(e)}")
            messagebox.showerror("Export Error", f"Failed to export WAV file:\n{str(e)}")

def main():
    root = tk.Tk()
    app = FSB4DebugGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
