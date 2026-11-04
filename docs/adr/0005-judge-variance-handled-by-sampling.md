# Judge variance is handled by sampling, not temperature

The LLM Judge is not deterministic, so it can be run several times per Run and each criterion's median kept, with the agreement between samples reported. Setting temperature to 0 would be the obvious fix, but Bedrock rejects any temperature setting for the current Judge model, Opus 5.5 ("temperature is deprecated for this model"). Sampling also exposes how confident a verdict is, which a single deterministic call would hide; the cost is one Judge call per sample.
