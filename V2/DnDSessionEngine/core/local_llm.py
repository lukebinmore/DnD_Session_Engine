from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import MODELS_DIR, LLM_REPO_ID, LLM_REPO_FOLDER, load_config
from huggingface_hub import snapshot_download
from huggingface_hub.utils import disable_progress_bars
from pathlib import Path
import onnxruntime_genai as og
import time
import json
import logging

logger = logging.getLogger(__name__)

MAX_NEW_TOKENS = 2048


def run_local_generation(model_ob, prompt, temperature=0.0, system_prompt=None, output=False):
    model = model_ob["model"]
    tokenizer = model_ob["tokenizer"]
    tokenizer_stream = tokenizer.create_stream()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    messages_json = json.dumps(messages)
    formatted_prompt = tokenizer.apply_chat_template(messages_json, add_generation_prompt=True)
    input_tokens = tokenizer.encode(formatted_prompt)

    params = og.GeneratorParams(model)
    params.set_search_options(
        max_length=len(input_tokens) + MAX_NEW_TOKENS, temperature=temperature, top_p=0.9, do_sample=(temperature > 0.0)
    )

    generator = og.Generator(model, params)
    generator.append_tokens(input_tokens)

    collected_chunks = []
    start_time = time.perf_counter()

    try:
        if not output:
            status = con.status("[highlight]Thinking...[/]", spinner="point")
            status.start()
        while not generator.is_done():
            generator.generate_next_token()
            token = generator.get_next_tokens()[0]
            chunk = tokenizer_stream.decode(token)
            if chunk:
                collected_chunks.append(chunk)
                if output:
                    con.print(chunk, end="", style="success")
        elapsed = time.perf_counter() - start_time
        if not output:
            status.stop()
            con.print(f"[highlight]Thought for {elapsed:.1f}s[/]")
    finally:
        del generator

    return "".join(collected_chunks).strip()


def load_model(engine_dir):
    logger.info(f"Loading ONNX GenAI model into runtime from: {engine_dir}")
    processor_id = load_config("LLM Processor ID")
    device_type = "CPU"
    try:
        config = og.Config(str(engine_dir))
        if processor_id != "-1":
            config.set_provider_option("dml", "device_id", processor_id)
            device_type = "GPU"
        model = og.Model(config)
        tokenizer = og.Tokenizer(model)

        logger.info(f"Local LLM initialised successfully on device: {device_type}")
        model_ob = {"model": model, "tokenizer": tokenizer}
        return model_ob
    except Exception as e:
        logger.error(f"Failed to load ONNX model into runtime!")
        raise e


def resolve_model_path(local_model_path):
    logger.info("Validating .onnx file path...")
    config_dirs = {p.parent for p in local_model_path.rglob("genai_config.json")}
    onnx_files = list(local_model_path.rglob("*.onnx"))

    if not onnx_files:
        logger.error(f"Failed to locate .onnx file!")
        raise FileNotFoundError(f"No .onnx file found in '{local_model_path}'")

    valid_candidates: list[Path] = [f for f in onnx_files if f.parent in config_dirs]

    if not valid_candidates:
        logger.error(f"Failed to locate genai_config.json file!")
        raise FileNotFoundError(f"No genai_config.json file found in '{local_model_path}'")

    selected_onnx = valid_candidates[0]
    if len(valid_candidates) > 1:
        for candidate in valid_candidates:
            if candidate.name.lower() == "model.onnx":
                selected_onnx = candidate
                break

    logger.info("File path validated!")
    return selected_onnx.parent


def download_model(repo_id, repo_subfolder=None, local_model_path=None):
    logger.info("Verifying local AI integrity, weights and structural manifests...")
    local_model_path.mkdir(parents=True, exist_ok=True)

    allow_patterns = []
    allow_patterns.append(f"{repo_subfolder}/*") if repo_subfolder else None

    try:
        with disable_progress_bars():
            snapshot_download(
                repo_id=repo_id,
                local_dir=str(local_model_path),
                allow_patterns=allow_patterns if allow_patterns else None,
            )

        logger.info(f"Model verification successful. Local path: {local_model_path}")

    except Exception as e:
        logger.error(f"Failed to verify or download the remote repositiry structure!")
        raise e


def initialise_llm():
    logger.info("Initialising Local Model...")
    repo_id = LLM_REPO_ID
    repo_folder = LLM_REPO_FOLDER
    model_name = repo_id.split("/")[-1]
    local_model_path = MODELS_DIR / model_name

    download_model(repo_id, repo_folder, local_model_path)
    engine_dir = resolve_model_path(local_model_path)
    model = load_model(engine_dir)

    logger.info("Initialising Local Model, Done!")

    return model
