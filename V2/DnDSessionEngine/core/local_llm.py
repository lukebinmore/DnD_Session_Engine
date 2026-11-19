from DnDSessionEngine.core.theme import con
from DnDSessionEngine.core.config import VULKAN_DIR, CPU_DIR, MODEL_DIR, load_config
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from rich.live import Live
import urllib.request
import zipfile
import re
import subprocess
import time
import json
import urllib.error
import logging

logger = logging.getLogger(__name__)

LLAMA_VERSION = "b12441"
RUNTIME_BUILDS = {
    "vulkan": f"llama-{LLAMA_VERSION}-bin-win-vulkan-x64.zip",
    "cpu": f"llama-{LLAMA_VERSION}-bin-win-cpu-x64.zip",
}
MODEL_NAME = "GPT-OSS-20B"
MODEL_URL = "https://huggingface.co/ggml-org/gpt-oss-20b-GGUF/resolve/main/gpt-oss-20b-MXFP4.gguf"
MODEL_FILE = "gpt-oss-20b-MXFP4.gguf"
MODEL_PATH = MODEL_DIR / MODEL_FILE

MODEL_PROFILES = {"small": {"context_size": 4068}, "medium": {"context_size": 8192}, "large": {"context_size": 16384}}

SELECTED_DEVICE = None
LLM_PROCESS = None

SYSTEM_PROMPT = """You are an intelligent Dungeons & Dragons campaign assistant.
Your purpose is to help the user understand, explore and develop their campaign.
You have access to campaign information retrieved from the user's campaign database.
The user's campaign information is your primary source of truth.
Treat supplied campaign information as authoritative.
Never invent established campaign facts or present assumptions as facts unless asked to.
Clearly distinguish between established facts and creative suggestions.
If the available information is insufficient, say so rather than guessing.
"""


def run_local_generation(prompt, context="No Context", temperature=0.5):
    url = "http://127.0.0.1:8000/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nCampaign Context:\n{context}"},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with con.status("[highlight]Thinking...[/]", spinner="point"):
            with urllib.request.urlopen(request, timeout=300) as response:
                result = json.loads(response.read().decode("utf-8"))
    except urllib.request.HTTPError as e:
        logger.error(f"Local model generation failed! Code: {e.code}")
        raise
    except Exception:
        logger.error("Local model generation failed!")
        raise

    content = result.get("choices", [])[0].get("message", {}).get("content")
    if not content:
        raise ValueError("Local model returned an empty response!")

    return content


def shutdown_llm_server():
    global LLM_PROCESS

    if LLM_PROCESS and LLM_PROCESS.poll() is None:
        logger.info("Shutting down local model server...")
        LLM_PROCESS.terminate()

        try:
            LLM_PROCESS.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Server didn't stop gracefully. Forcing shutdown...")
            LLM_PROCESS.kill()
            LLM_PROCESS.wait()

        logger.info("Local model server shut down successfully!")

    LLM_PROCESS = None


def launch_llm_server():
    global LLM_PROCESS
    logger.info("Starting local model server...")

    if SELECTED_DEVICE is None:
        raise RuntimeError("Local model has no device set!")

    if LLM_PROCESS and LLM_PROCESS.poll() is None:
        logger.info("Local model server is already running!")
        return

    runtime_dir = CPU_DIR if SELECTED_DEVICE == "cpu" else VULKAN_DIR
    server_path = runtime_dir / "llama-server.exe"

    model_profile = MODEL_PROFILES[load_config("Model Size")]

    command = [
        str(server_path),
        "--model",
        str(MODEL_PATH),
        "--n-gpu-layers",
        "0" if SELECTED_DEVICE == "cpu" else "99",
        "--ctx-size",
        str(model_profile["context_size"]),
        "--parallel",
        "1",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    if isinstance(SELECTED_DEVICE, dict):
        command.extend(["--device", SELECTED_DEVICE["id"]])

    logger.info("Starting local model server subprocess...")
    log_file = open(runtime_dir / "llama-server.log", "w", encoding="utf-8")
    LLM_PROCESS = subprocess.Popen(
        command, stdout=log_file, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW
    )
    logger.info("Local model server subprocess launched successfully!")

    logger.info("Waiting for local model server boot...")
    health_url = "http://127.0.0.1:8000/health"
    timeout = time.monotonic() + 300
    while time.monotonic() < timeout:
        if LLM_PROCESS.poll() is not None:
            raise RuntimeError(f"Local model server exited unexpectedly! (Code: {LLM_PROCESS.returncode})")
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    logger.info("Local model server is ready!")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        finally:
            log_file.close()

        time.sleep(1)
    shutdown_llm_server()
    raise TimeoutError("Local model server failed to start within 5 minutes!")


def download_model():
    logger.info(f"Checking {MODEL_NAME}...")

    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 0:
        logger.info(f"{MODEL_NAME} already downloaded. Skipping download!")
        return

    temp_path = MODEL_PATH.with_suffix(".part")
    downloaded_bytes = temp_path.stat().st_size if temp_path.exists() else 0
    request = urllib.request.Request(
        MODEL_URL, headers={"Range": f"bytes={downloaded_bytes}-"} if downloaded_bytes else {}
    )

    logger.info(f"Downloading {MODEL_NAME} from Hugging Face...")
    try:
        with urllib.request.urlopen(request) as response:
            if downloaded_bytes:
                if response.status != 206:
                    raise RuntimeError("Server did not honour resume request!")

                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                if not match or int(match.group(1)) != downloaded_bytes:
                    raise RuntimeError("Invalid resume response!")

                total_size = int(match.group(3))
                if int(match.group(2)) != total_size - 1:
                    raise RuntimeError("Incomplete byte range returned!")
            else:
                if response.status != 200:
                    raise RuntimeError("Unexpected download response!")

                total_size = int(response.headers.get("Content-Length", 0))

            block_size = 1024 * 1024
            completed = downloaded_bytes
            with Progress(
                TextColumn("[menu.key]{task.description}[/]"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=con,
            ) as progress:
                task = progress.add_task(f"Downloading {MODEL_NAME}...", total=total_size, completed=completed)
                with temp_path.open("ab" if downloaded_bytes else "wb") as model_file:
                    while True:
                        block = response.read(block_size)
                        if not block:
                            break

                        model_file.write(block)
                        completed += len(block)
                        progress.update(task, completed=completed)

        if temp_path.stat().st_size != total_size:
            raise RuntimeError(
                f"Incomplete download: expected {total_size} bytes, " f"received {temp_path.stat().st_size} bytes!"
            )

        temp_path.rename(MODEL_PATH)
        logger.info(f"{MODEL_NAME} downloaded successfully!")

    except Exception:
        logger.error(f"Failed to download {MODEL_NAME}!")
        raise


def detect_hardware():
    logger.info("Detecting available hardware...")
    result = subprocess.run([str(VULKAN_DIR / "llama-server.exe"), "--list-devices"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("Hardware detection failed. Falling back to CPU!")
        return "cpu"
    logger.info(f"{result.stdout}")
    devices = []
    for match in re.finditer(r"Vulkan(\d+):\s*(.*?)\s*\((\d+) MiB, (\d+) MiB free\)", result.stdout):
        device_id, name, total_memory, free_memory = match.groups()
        devices.append(
            {
                "id": f"Vulkan{device_id}",
                "name": name,
                "total_memory": int(total_memory),
                "free_memory": int(free_memory),
                "dedicated": "UHD" not in name,
            }
        )

    if not devices:
        logger.info("No compatible GPU's detected. Using CPU!")
        return "cpu"

    dedicated_gpus = [device for device in devices if device["dedicated"]]
    gpu_candidates = dedicated_gpus if dedicated_gpus else devices
    selected_gpu = max(gpu_candidates, key=lambda device: device["free_memory"])
    logger.info(f"Selected GPU: {selected_gpu['name']} ({selected_gpu["free_memory"]}) MiB free)")
    return selected_gpu


def download_runtime(build_name, archive_name):
    logger.info(f"Preparing {build_name} runtime installation...")
    target_dir = VULKAN_DIR if build_name == "vulkan" else CPU_DIR
    version_file = target_dir / "VERSION.txt"
    if (
        (target_dir / "llama-server.exe").exists()
        and version_file.exists()
        and version_file.read_text().strip() == LLAMA_VERSION
    ):
        logger.info(f"{build_name} runtime already exists at the correct version. Skipping download!")
        return

    url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_VERSION}/{archive_name}"
    archive_path = target_dir.parent / archive_name
    try:
        try:
            logger.info(f"Downloading {build_name} runtime from GitHub...")
            with Progress(
                TextColumn("{task.description}"),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=con,
            ) as progress:
                task = progress.add_task(f"Downloading {build_name} runtime...", total=0)
                urllib.request.urlretrieve(url, archive_path, reporthook=update_progress(progress, task))
            logger.info(f"{build_name} runtime downloaded successfully!")
        except Exception:
            logger.error(f"Failed to download {build_name} runetime!")
            raise

        try:
            logger.info(f"Extracting {build_name} runtime...")
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(target_dir)
            logger.info(f"{build_name} runtime extracted successfully!")
        except Exception:
            logger.error(f"Failed to extract {build_name} runtime!")
            raise

        if not (target_dir / "llama-server.exe").exists():
            raise FileNotFoundError(f"llama-server.exe missing from {target_dir}!")

        version_file.write_text(LLAMA_VERSION)
        logger.info(f"Installed runtime version recorded: {LLAMA_VERSION}")

        logger.info(f"{build_name} runtime verified successfully!")
    finally:
        if archive_path.exists():
            archive_path.unlink()
            logger.info(f"Removed temprary archive: {archive_path}!")


def update_progress(progress, task, offset=0):
    def callback(block_num, block_size, total_size):
        if total_size > 0:
            progress.update(task, total=total_size, completed=min(offset + block_num * block_size, total_size))

    return callback


def initialise_llm():
    global SELECTED_DEVICE
    logger.info("Initialising Local Model...")
    download_runtime("vulkan", RUNTIME_BUILDS["vulkan"])
    SELECTED_DEVICE = detect_hardware()
    if SELECTED_DEVICE == "cpu":
        download_runtime("cpu", RUNTIME_BUILDS["cpu"])
    download_model()
    logger.info("Initialising Local Model, Done!")
