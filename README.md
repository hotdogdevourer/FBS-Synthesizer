# Formant-based Speech Synthesis in Python 3.11

A Python 3.11 script for formant-based speech synthesis, designed for experimentation and learning about text-to-speech at the phoneme/formant level.

⚠️ Windows-style file paths are assumed. Minor tweaks may be required for other OSes.

⚠️ This is a barely-debugged project. Expect bugs, but it works for experiments.

# Installation

You need Python 3.11 and the following packages:

```pip install numpy scipy```


Clone this repo:
```
git clone <your-repo-url>
cd <repo-folder>
```

# Features

Converts text to phonemes using a custom WORD_MAP.

Converts phonemes to phoneme specifications (PHX format) with pitch contours and formants.

Synthesizes speech with:

Glottal pulse trains for voiced sounds

Filtered noise for unvoiced/fricatives

Stop consonant bursts

Basic formant filtering (f1, f2, f3)

Saves audio as WAV files.

Supports custom voices via JSON files.

Legacy support for .phn bytecode files (1 byte/phoneme, no pitch contours).

# How it works

1. **Text → Phonemes**
Uses WORD_MAP to convert lowercase English text to a sequence of phonemes.
Example: "hello world" → ['SIL', 'HH', 'EH', 'L', 'AO', 'OW', 'SIL', 'W', 'ER', 'L', 'D', 'SIL'].

2. **Phonemes → Specifications**
Each phoneme gets a spec dict:

{
    'phoneme': 'AH',
    'duration': 0.14,
    'pitch_contour': [115.0],
    'num_pitch_points': 1,
    'f1': 700.0,
    'f2': 1100.0,
    'f3': 2400.0,
    'voiced': True
}


pitch_contour allows variable pitch over the phoneme duration.

Formants (f1, f2, f3) shape the vowel/consonant sound.

3. **Phoneme synthesis**

Voiced phonemes: glottal pulse + formant filtering.

Unvoiced/fricatives: filtered noise.

Stops: burst noise + optional voicing/aspiration.

Envelope applied to prevent clicks.

4. **Audio Output**

All phonemes concatenated.

Final lowpass filter applied.

Save as WAV with save_wav(filename, audio).

# File Formats
# PHX (Parameterized phonemes)

Header: DE AD BE EF

50 bytes per phoneme:

1 byte phoneme ID

4 bytes duration (float32)

1 byte num pitch points

8×4 bytes pitch points (float32)

3×4 bytes formants f1,f2,f3 (float32)

# PHN (Legacy bytecode)

Header: FE EB DA ED

1 byte: voice name length

N bytes: voice name UTF-8

1 byte per phoneme

⚠️ No pitch contour or formant info.

# Example Usage

**Text to PHX + WAV**
```python
from main import VOICE_REGISTRY, FormantSynthesizer, text_to_phonemes, phonemes_to_spec, save_wav

text = "hello world"
phonemes = text_to_phonemes(text)
specs = phonemes_to_spec(phonemes, VOICE_REGISTRY.current_voice)
synth = FormantSynthesizer(VOICE_REGISTRY.current_voice)
audio = synth.synthesize_from_specs(specs)
save_wav("hello_world.wav", audio)
```

Load custom voice

```python
from main import Voice

voice = Voice.load("voices/custom_voice.json")
VOICE_REGISTRY.voices[voice.name] = voice
VOICE_REGISTRY.set_current_voice(voice.name)
```

# Notes / Limitations

Only basic English phonemes supported.

Windows-style paths assumed.

Minimal error handling; invalid phonemes or files may crash the program.

Realistic prosody is very limited; mainly robotic/experimental voices.

Works best with short sentences.

# License

**MIT** License
 – free to hack, experiment, or use as a base for projects.
