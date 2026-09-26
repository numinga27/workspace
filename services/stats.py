from models import Task, Milestone, Report, Todo, ProjectMember, Message


def get_todo_stats(project_id):
    todos = Todo.query.filter_by(project_id=project_id).all()
    return {
        'total': len(todos),
        'done': sum(1 for t in todos if t.is_done),
        'overdue': sum(1 for t in todos if t.is_overdue),
        'new': sum(1 for t in todos if not t.is_done and not t.is_overdue),
        'todos': todos,
    }


def calculate_project_stats(project):
    tasks = Task.query.filter_by(project_id=project.id, parent_task_id=None).all()
    all_tasks = Task.query.filter_by(project_id=project.id).all()
    milestones = Milestone.query.filter_by(project_id=project.id).order_by(Milestone.order_index).all()
    reports = Report.query.filter_by(project_id=project.id).order_by(Report.created_at.desc()).all()
    todos = Todo.query.filter_by(project_id=project.id).all()

    completed_tasks = [t for t in tasks if t.status == 'completed']
    in_progress_tasks = [t for t in tasks if t.status == 'in_progress']
    overdue_tasks = [t for t in tasks if t.is_overdue]
    new_tasks = [t for t in tasks if t.status == 'new' and not t.is_overdue]

    completed_milestones = [m for m in milestones if m.is_completed]
    overdue_milestones = [m for m in milestones if m.is_overdue]

    on_time_reports = [r for r in reports if r.reason == 'on_track']
    delayed_reports = [r for r in reports if r.reason != 'on_track']

    todo_stats = get_todo_stats(project.id)

    return {
        'tasks': tasks, 'milestones': milestones, 'reports': reports, 'todos': todos,
        'completed_tasks_list': completed_tasks, 'in_progress_tasks_list': in_progress_tasks,
        'overdue_tasks_list': overdue_tasks, 'new_tasks_list': new_tasks,
        'total_tasks': len(tasks), 'total_subtasks': len(all_tasks) - len(tasks),
        'completed_tasks': len(completed_tasks), 'in_progress_tasks': len(in_progress_tasks),
        'overdue_tasks': len(overdue_tasks), 'new_tasks': len(new_tasks),
        'total_milestones': len(milestones), 'completed_milestones': len(completed_milestones),
        'overdue_milestones': len(overdue_milestones),
        'total_reports': len(reports), 'on_time_reports': len(on_time_reports),
        'delayed_reports': len(delayed_reports),
        'total_todos': len(todos), 'completed_todos': len([t for t in todos if t.is_done]),
        'todo_total': todo_stats['total'], 'todo_done': todo_stats['done'],
        'todo_overdue': todo_stats['overdue'], 'todo_new': todo_stats['new'],
        'completion_percentage': project.completion_percentage,
    }


def calculate_task_stats(task):
    subtasks = Task.query.filter_by(parent_task_id=task.id).all()
    done = [t for t in subtasks if t.status == 'completed']
    overdue = [t for t in subtasks if t.is_overdue]
    in_progress = [t for t in subtasks if t.status == 'in_progress']
    new = [t for t in subtasks if t.status == 'new' and not t.is_overdue]

    return {
        'subtasks': subtasks, 'total': len(subtasks),
        'done': len(done), 'overdue': len(overdue),
        'in_progress': len(in_progress), 'new': len(new),
        'done_list': done, 'overdue_list': overdue,
        'in_progress_list': in_progress, 'new_list': new,
    }


def calculate_employee_stats(project, user):
    tasks = Task.query.filter_by(project_id=project.id, assigned_to=user.id).all()
    subtasks = [t for t in tasks if t.parent_task_id]
    todos = Todo.query.filter_by(project_id=project.id, assigned_to=user.id).all()
    messages = Message.query.filter_by(project_id=project.id, user_id=user.id).all()
    reports = Report.query.filter_by(project_id=project.id, author_id=user.id).all()

    completed_tasks = [t for t in tasks if t.status == 'completed']
    in_progress_tasks = [t for t in tasks if t.status == 'in_progress']
    overdue_tasks = [t for t in tasks if t.is_overdue]

    activity_score = (
        len(messages) * 1 + len(completed_tasks) * 5 + len(in_progress_tasks) * 3 +
        len(todos) * 1 + len(reports) * 3
    )

    member = ProjectMember.query.filter_by(user_id=user.id, project_id=project.id).first()

    total_tasks = len(tasks)
    completion_rate = (len(completed_tasks) / total_tasks * 100) if total_tasks else 0
    overdue_rate = (len(overdue_tasks) / total_tasks * 100) if total_tasks else 0

    return {
        'total_tasks': total_tasks, 'completed_tasks': len(completed_tasks),
        'in_progress_tasks': len(in_progress_tasks), 'overdue_tasks': len(overdue_tasks),
        'total_subtasks': len(subtasks), 'total_todos': len(todos),
        'completed_todos': len([t for t in todos if t.is_done]),
        'total_messages': len(messages), 'total_reports': len(reports),
        'activity_score': activity_score,
        'completion_rate': round(completion_rate, 1),
        'overdue_rate': round(overdue_rate, 1),
        'role_in_project': member.role_display if member else 'Не в проекте',
        'tasks': tasks, 'todos': todos, 'messages': messages, 'reports': reports,
    }