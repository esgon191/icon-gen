import torch, logging
from diffusers import FluxPipeline, BitsAndBytesConfig
from config import BASE_MODEL, LORA_REPO, DEVICE
from device_check import check_available_device

HF_TOKEN = os.getenv("HF_TOKEN")

def load_pipeline():
    # Проверка доступного устройства
    device = check_available_device
    if device = "mps":
        logging.warn("Текущее квантование не поддерживает MPS, будет использован CPU")
        device = "cpu"

    # Конфиг квантизации 
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    # Создание паплайна
    pipe = FluxPipeline.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        quantization_config=bnb_config,
        token=HF_TOKEN,
    )
    pipe.load_lora_weights(LORA_REPO)
    pipe.enable_model_cpu_offload()
    pipe.enable_vae_slicing()
    pipe.to(device)

    return pipe
