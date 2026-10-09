# Third-party components

First-party application, deployment scripts and documentation are released under GPL-3.0-or-later. The license does not relicense upstream software, models, datasets or trademarks. This source release contains no model weights, Asterisk binaries or downloaded spam lists. Containers download/install components separately; review the upstream terms for your intended use and for any binary distribution.

| Component | Upstream reference / terms |
| --- | --- |
| Piper 1.x | [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl), GPL-3.0-or-later |
| Fresh-install voice | [en_US-ljspeech-high model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/high/MODEL_CARD); dataset is public domain |
| Legacy Lessac voice | [Dataset research license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html); review before continued use beyond research; not bundled |
| Qwen3 1.7B | [Model card](https://huggingface.co/Qwen/Qwen3-1.7B), Apache-2.0 |
| Ollama | [Upstream](https://github.com/ollama/ollama), MIT |
| faster-whisper | [Upstream](https://github.com/SYSTRAN/faster-whisper), MIT; inference dependencies have their own licenses |
| Whisper | [Upstream](https://github.com/openai/whisper), MIT |
| Asterisk | [Upstream licensing](https://docs.asterisk.org/About-the-Project/Licensing/), generally GPLv2; bundled libraries have separate terms |
| FFmpeg | [Legal/licensing](https://ffmpeg.org/legal.html), depends on build configuration |
| CallShield | [Project](https://github.com/SysAdminDoc/CallShield); upstream software notice in `integrations/callshield/LICENSE-CallShield.txt`; downloaded feed/data terms are source-specific |

Python packages such as FastAPI, Uvicorn, httpx, websockets, PyAV and cryptography retain their upstream licenses. Base Ubuntu/Python images and system packages contain further notices. License text for redistributed binaries must be supplied as required by those components; this source repository alone is not a complete binary-distribution notice bundle.

The default LJ Speech voice may have different speed and sound from the earlier Lessac benchmark. Select an alternative using `PIPER_VOICE` only after checking that voice's model card and underlying dataset terms. No blanket permission for all Piper voices is implied.
