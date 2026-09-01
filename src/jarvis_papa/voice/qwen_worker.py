from __future__ import annotations

import argparse
import base64
from pathlib import Path


def decode(value: str) -> str:
    return base64.b64decode(value.encode("ascii")).decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen3-TTS worker for Jarvis Papa")
    parser.add_argument("--text-b64", required=True)
    parser.add_argument("--instruction-b64", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--language", default="French")
    parser.add_argument("--speaker", default="Serena")
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    text = decode(args.text_b64)
    instruction = decode(args.instruction_b64) if args.instruction_b64 else ""
    dtype = torch.bfloat16 if str(args.device).startswith("cuda") else torch.float32
    load_kwargs: dict[str, object] = {
        "device_map": args.device,
        "dtype": dtype,
    }
    if str(args.device).startswith("cuda"):
        try:
            import flash_attn  # noqa: F401
        except ImportError:
            pass
        else:
            load_kwargs["attn_implementation"] = "flash_attention_2"

    model = Qwen3TTSModel.from_pretrained(args.model, **load_kwargs)
    if "VoiceDesign" in args.model:
        wavs, sample_rate = model.generate_voice_design(
            text=text,
            language=args.language,
            instruct=instruction,
        )
    else:
        kwargs: dict[str, object] = {
            "text": text,
            "language": args.language,
            "speaker": args.speaker,
        }
        if "1.7B" in args.model and instruction:
            kwargs["instruct"] = instruction
        wavs, sample_rate = model.generate_custom_voice(**kwargs)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), wavs[0], sample_rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
