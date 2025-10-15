import paddle
import time

print("\n" + "=" * 50)
print("🔍 ПРОВЕРКА GPU")
print("=" * 50 + "\n")

print(f"PaddlePaddle версия: {paddle.__version__}")
print(f"CUDA доступна: {paddle.is_compiled_with_cuda()}")

if paddle.is_compiled_with_cuda():
    gpu_count = paddle.device.cuda.device_count()
    print(f"GPU count: {gpu_count}")

    paddle.device.set_device('gpu:0')
    print("✅ GPU активирован!")

    x = paddle.randn([1000, 1000])
    start = time.time()
    y = paddle.matmul(x, x)
    paddle.device.synchronize()   # ✅ новая версия
    elapsed = (time.time() - start) * 1000

    print(f"⚡ Тест GPU: {elapsed:.2f} мс")
    print("\n✅ ВСЁ РАБОТАЕТ!\n")
else:
    print("\n❌ CUDA НЕ ДОСТУПНА!")
    print("Проверь установку GPU-версии Paddle:")
    print("pip show paddlepaddle-gpu\n")
