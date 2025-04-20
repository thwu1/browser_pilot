import pytest
from scheduler import (
    SchedulerType,
    SchedulerOutput,
    make_scheduler,
    RoundRobinScheduler
)
from worker import BrowserWorkerTask

def test_make_scheduler():
    """Test scheduler factory function"""
    # Test creating round robin scheduler
    config = {"type": SchedulerType.ROUND_ROBIN, "max_batch_size": 5, "n_workers": 3}
    scheduler = make_scheduler(config)
    assert isinstance(scheduler, RoundRobinScheduler)
    assert scheduler.batch_size == 5
    assert scheduler.n_workers == 3

    # Test invalid scheduler type
    with pytest.raises(AssertionError):
        make_scheduler({"type": "invalid_type", "max_batch_size": 5, "n_workers": 3})

def test_round_robin_scheduler_init():
    """Test RoundRobinScheduler initialization"""
    scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)
    assert scheduler.batch_size == 5
    assert scheduler.n_workers == 3
    assert scheduler.scheduler_type == SchedulerType.ROUND_ROBIN

def test_round_robin_scheduler_schedule():
    """Test RoundRobinScheduler scheduling logic"""
    scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)
    
    # Create test tasks
    tasks = [
        BrowserWorkerTask(task_id=f"task_{i}", command="test_command")
        for i in range(5)
    ]
    
    # Test with all new tasks (no previous worker assignments)
    last_assigned_workers = [-1] * len(tasks)
    worker_status = [{"status": "idle"} for _ in range(3)]
    
    scheduled_tasks, output = scheduler.schedule(
        tasks,
        last_assigned_workers,
        3,  # n_workers
        worker_status
    )
    
    # Verify output structure
    assert isinstance(output, SchedulerOutput)
    assert len(output.task_assignments) == len(tasks)
    
    # Verify round-robin assignment
    expected_assignments = {
        "task_0": 0,
        "task_1": 1,
        "task_2": 2,
        "task_3": 0,
        "task_4": 1,
    }
    assert output.task_assignments == expected_assignments

def test_round_robin_scheduler_with_existing_assignments():
    """Test RoundRobinScheduler with existing worker assignments"""
    scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)
    
    tasks = [
        BrowserWorkerTask(task_id=f"task_{i}", command="test_command")
        for i in range(3)
    ]
    
    # Test with some existing worker assignments
    last_assigned_workers = [1, -1, 2]  # task_0 was on worker 1, task_2 was on worker 2
    worker_status = [{"status": "idle"} for _ in range(3)]
    
    scheduled_tasks, output = scheduler.schedule(
        tasks,
        last_assigned_workers,
        3,
        worker_status
    )
    
    # Verify assignments respect existing assignments
    assert output.task_assignments["task_0"] == 1  # Should keep existing assignment
    assert output.task_assignments["task_2"] == 2  # Should keep existing assignment
    # task_1 should get a new assignment
    assert output.task_assignments["task_1"] in [0, 1, 2]

def test_scheduler_output():
    """Test SchedulerOutput functionality"""
    # Test creation
    assignments = {"task_1": 0, "task_2": 1}
    metadata = {"some_key": "some_value"}
    output = SchedulerOutput(task_assignments=assignments, metadata=metadata)
    
    # Test attributes
    assert output.task_assignments == assignments
    assert output.metadata == metadata
    
    # Test from_dict factory method
    output2 = SchedulerOutput.from_dict(assignments)
    assert output2.task_assignments == assignments
    assert output2.metadata is None

def test_scheduler_with_empty_tasks():
    """Test scheduler behavior with empty task list"""
    scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)
    
    scheduled_tasks, output = scheduler.schedule(
        [],  # empty task list
        [],  # empty last_assigned_workers
        3,
        [{"status": "idle"} for _ in range(3)]
    )
    
    assert len(scheduled_tasks) == 0
    assert len(output.task_assignments) == 0

def test_scheduler_stress():
    """Stress test the scheduler with many tasks"""
    scheduler = RoundRobinScheduler(batch_size=100, n_workers=5)
    
    # Create many tasks
    num_tasks = 1000
    tasks = [
        BrowserWorkerTask(task_id=f"task_{i}", command="test_command")
        for i in range(num_tasks)
    ]
    last_assigned_workers = [-1] * num_tasks
    worker_status = [{"status": "idle"} for _ in range(5)]
    
    # Schedule all tasks
    scheduled_tasks, output = scheduler.schedule(
        tasks,
        last_assigned_workers,
        5,
        worker_status
    )
    
    # Verify all tasks were assigned
    assert len(output.task_assignments) == num_tasks
    
    # Verify worker distribution is roughly even
    worker_counts = [0] * 5
    for worker_id in output.task_assignments.values():
        worker_counts[worker_id] += 1
    
    # Check that the difference between max and min assignments is reasonable
    assignment_diff = max(worker_counts) - min(worker_counts)
    assert assignment_diff <= 1  # Should be perfectly balanced or off by at most 1

# def test_scheduler_with_invalid_inputs():
#     """Test scheduler behavior with invalid inputs"""
#     scheduler = RoundRobinScheduler(batch_size=5, n_workers=3)
    
#     # Test with mismatched tasks and last_assigned_workers lengths
#     tasks = [BrowserWorkerTask(task_id="task_1", command="test_command")]
#     with pytest.raises(AssertionError):
#         scheduler.schedule(tasks, [], 3, [{"status": "idle"} for _ in range(3)])
    
#     # Test with invalid worker index in last_assigned_workers
#     with pytest.raises(AssertionError):
#         scheduler.schedule(
#             tasks,
#             [5],  # worker index 5 is invalid for n_workers=3
#             3,
#             [{"status": "idle"} for _ in range(3)]
#         ) 