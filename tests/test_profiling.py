import asyncio
from worker_client import WorkerClient
import uuid
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import random
import time


def calculate_metrics(outputs):
    worker_recv_to_start_process = [
        output["profile"]["worker_start_process_timestamp"]
        - output["profile"]["worker_recv_timestamp"]
        for output in outputs
    ]
    assert all(
        [x >= 0 for x in worker_recv_to_start_process]
    ), f"worker_recv_to_start_process: {worker_recv_to_start_process}"
    worker_start_process_to_finish = [
        output["profile"]["worker_finish_timestamp"]
        - output["profile"]["worker_start_process_timestamp"]
        for output in outputs
    ]
    worker_finish_to_send = [
        output["profile"]["worker_send_timestamp"]
        - output["profile"]["worker_finish_timestamp"]
        for output in outputs
    ]

    # Calculate and print summary statistics for each portion
    def stats(arr, name):
        arr = [x for x in arr if x is not None]
        if not arr:
            print(f"No data for {name}")
            return
        print(
            f"{name}: avg={sum(arr)/len(arr):.4f}s, min={min(arr):.4f}s, max={max(arr):.4f}s, p95={sorted(arr)[int(0.95*len(arr))-1]:.4f}s"
        )

    print("--- Profiling Breakdown ---")
    stats(worker_recv_to_start_process, "recv_to_start")
    stats(worker_start_process_to_finish, "start_to_finish")
    stats(worker_finish_to_send, "finish_to_send")

    # Calculate total time for each task and percentage of each portion
    total_times = [
        recv + start + send
        for recv, start, send in zip(
            worker_recv_to_start_process,
            worker_start_process_to_finish,
            worker_finish_to_send,
        )
    ]
    total = sum(total_times)
    recv_pct = sum(worker_recv_to_start_process) / total * 100 if total > 0 else 0
    start_pct = sum(worker_start_process_to_finish) / total * 100 if total > 0 else 0
    send_pct = sum(worker_finish_to_send) / total * 100 if total > 0 else 0
    print(
        f"Percentage breakdown: recv_to_start={recv_pct:.2f}%, start_to_finish={start_pct:.2f}%, finish_to_send={send_pct:.2f}%"
    )
    print("--------------------------")

    return (
        worker_recv_to_start_process,
        worker_start_process_to_finish,
        worker_finish_to_send,
    )


def analyze_by_command(outputs):
    """Group outputs by command and compute/plot metrics per command."""
    commands = sorted(set(o["command"] for o in outputs))
    stats = {}
    for cmd in commands:
        outs = [o for o in outputs if o["command"] == cmd]
        recv, start, fin = calculate_metrics(outs)
        stats[cmd] = (recv, start, fin)
    # Print summary stats
    for cmd, (recv, start, fin) in stats.items():
        print(
            f"{cmd}: recv->start avg={sum(recv)/len(recv):.4f}s, start->finish avg={sum(start)/len(start):.4f}s, finish->send avg={sum(fin)/len(fin):.4f}s"
        )
    # Plot per-command boxplots
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    metric_names = ["recv_to_start", "start_to_finish", "finish_to_send"]
    for i, label in enumerate(metric_names):
        data = [stats[cmd][i] for cmd in commands]
        axes[i].boxplot(data, labels=commands)
        axes[i].set_title(label)
        axes[i].set_ylabel("Time (s)")
        axes[i].tick_params(axis="x", rotation=45)
    fig.tight_layout()
    plt.savefig("profiling_metrics_by_cmd.png")
    print("Saved profiling_metrics_by_cmd.png")


async def goto_url_helper(client, context_id, page_id, url):
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    # Tag browser_navigate
    cmd = "browser_navigate"
    client.send(
        [
            {
                "command": "browser_navigate",
                "task_id": task_id,
                "context_id": context_id,
                "page_id": page_id,
                "params": {"url": url, "timeout": 30000},
            }
        ],
        index=0,
    )
    output = await client.get_output_with_task_id(task_id, timeout=30)
    output["command"] = cmd
    return output, page_id


async def get_observation_helper(client, context_id, page_id, observation_type):
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    # Tag browser_observation
    cmd = "browser_observation"
    client.send(
        [
            {
                "command": "browser_observation",
                "task_id": task_id,
                "context_id": context_id,
                "page_id": page_id,
                "params": {"observation_type": observation_type},
            }
        ],
        index=0,
    )
    output = await client.get_output_with_task_id(task_id)
    output["command"] = cmd
    return output, page_id


async def create_context_helper(client):
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    context_id = f"{uuid.uuid4().hex[:8]}"
    # Tag output with command
    cmd = "create_context"
    client.send(
        [
            {
                "command": "create_context",
                "task_id": task_id,
                "context_id": context_id,
            }
        ],
        index=0,
    )
    output = await client.get_output_with_task_id(task_id)
    output["command"] = cmd
    return output, context_id


def test_profiling_metrics():
    input_path = "ipc://input_sync"
    output_path = "ipc://output_sync"
    num_workers = 1

    client = WorkerClient(input_path, output_path, num_workers)

    async def go_to_youtube_bilibili_return_html():
        # await asyncio.sleep(5*random.random())
        outputs = []
        output, context_id = await create_context_helper(client)
        outputs.append(output)
        assert output["result"]["success"] == True
        # print(f"Created context: {output}")
        # context_id = output["context_id"]

        output, page_id = await goto_url_helper(
            client, context_id, None, "https://www.youtube.com"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await get_observation_helper(
            client, context_id, page_id, "html"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await goto_url_helper(
            client, context_id, page_id, "https://www.bilibili.com"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await get_observation_helper(
            client, context_id, page_id, "html"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await goto_url_helper(
            client, context_id, page_id, "https://www.nytimes.com"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await get_observation_helper(
            client, context_id, page_id, "html"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await goto_url_helper(
            client, context_id, page_id, "https://www.reddit.com"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await get_observation_helper(
            client, context_id, page_id, "html"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await goto_url_helper(
            client, context_id, page_id, "https://www.amazon.com"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await get_observation_helper(
            client, context_id, page_id, "html"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await goto_url_helper(
            client, context_id, page_id, "https://www.apple.com"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        output, page_id = await get_observation_helper(
            client, context_id, page_id, "html"
        )
        outputs.append(output)
        assert output["result"]["success"] == True

        return outputs

    async def main():
        start_time = time.time()
        outputs = await asyncio.gather(
            *[go_to_youtube_bilibili_return_html() for _ in range(64)]
        )
        end_time = time.time()
        print(f"Total time: {end_time - start_time:.2f}s")
        outputs_flattened = [output for task in outputs for output in task]
        print(f"Outputs: {len(outputs_flattened)}")
        # Visualize profiling metrics
        recv_to_start, start_to_finish, finish_to_send = calculate_metrics(
            outputs_flattened
        )
        plt.figure(figsize=(10, 6))
        plt.boxplot(
            [recv_to_start, start_to_finish, finish_to_send],
            labels=["recv_to_start", "start_to_finish", "finish_to_send"],
        )
        plt.ylabel("Time (s)")
        plt.title("Worker Profiling Metrics")
        plt.savefig("profiling_metrics.png")
        print("Saved profiling_metrics.png")
        # Analyze profiling per command
        analyze_by_command(outputs_flattened)

    asyncio.run(main())
    client.close()


if __name__ == "__main__":
    test_profiling_metrics()
