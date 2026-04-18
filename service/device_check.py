import torch

def check_available_device():
    """
    Возвращает максимально предпочтительный из доступных устройств:
        cuda на сервисе с NVIDIA
        mps на сервисе на базе M-чипов
        иначе cpu
    """
    device = None
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    return device
