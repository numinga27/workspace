#!/bin/bash
cd templates/pdf

# Те же замены, но для *.html в подпапке pdf/
sed -i '' "s/url_for('login')/url_for('auth.login')/g" *.html
sed -i '' "s/url_for('register')/url_for('auth.register')/g" *.html
sed -i '' "s/url_for('register',/url_for('auth.register',/g" *.html
sed -i '' "s/url_for('logout')/url_for('auth.logout')/g" *.html

sed -i '' "s/url_for('dashboard')/url_for('dashboard.dashboard')/g" *.html
sed -i '' "s/url_for('dashboard',/url_for('dashboard.dashboard',/g" *.html

sed -i '' "s/url_for('my_tasks')/url_for('tasks.my_tasks')/g" *.html
sed -i '' "s/url_for('view_task'/url_for('tasks.view_task'/g" *.html
sed -i '' "s/url_for('update_task_status'/url_for('tasks.update_task_status'/g" *.html
sed -i '' "s/url_for('update_task_comment'/url_for('tasks.update_task_comment'/g" *.html
sed -i '' "s/url_for('delete_task'/url_for('tasks.delete_task'/g" *.html
sed -i '' "s/url_for('user_all_tasks'/url_for('tasks.user_all_tasks'/g" *.html

sed -i '' "s/url_for('create_project')/url_for('projects.create_project')/g" *.html
sed -i '' "s/url_for('view_project'/url_for('projects.view_project'/g" *.html
sed -i '' "s/url_for('edit_project'/url_for('projects.edit_project'/g" *.html
sed -i '' "s/url_for('delete_project'/url_for('projects.delete_project'/g" *.html
sed -i '' "s/url_for('create_milestone'/url_for('projects.create_milestone'/g" *.html
sed -i '' "s/url_for('toggle_milestone'/url_for('projects.toggle_milestone'/g" *.html
sed -i '' "s/url_for('delete_milestone'/url_for('projects.delete_milestone'/g" *.html
sed -i '' "s/url_for('create_task'/url_for('projects.create_task'/g" *.html

sed -i '' "s/url_for('my_calendar')/url_for('calendar.my_calendar')/g" *.html
sed -i '' "s/url_for('my_calendar_json')/url_for('calendar.my_calendar_json')/g" *.html
sed -i '' "s/url_for('create_personal_event')/url_for('calendar.create_personal_event')/g" *.html
sed -i '' "s/url_for('create_event'/url_for('calendar.create_event'/g" *.html
sed -i '' "s/url_for('events_json'/url_for('calendar.events_json'/g" *.html
sed -i '' "s/url_for('delete_event'/url_for('calendar.delete_event'/g" *.html

sed -i '' "s/url_for('customers_list')/url_for('customers.customers_list')/g" *.html
sed -i '' "s/url_for('create_customer')/url_for('customers.create_customer')/g" *.html
sed -i '' "s/url_for('create_customer',/url_for('customers.create_customer',/g" *.html
sed -i '' "s/url_for('edit_customer'/url_for('customers.edit_customer'/g" *.html

sed -i '' "s/url_for('project_settings'/url_for('team.project_settings'/g" *.html
sed -i '' "s/url_for('invite_user'/url_for('team.invite_user'/g" *.html
sed -i '' "s/url_for('remove_member'/url_for('team.remove_member'/g" *.html
sed -i '' "s/url_for('change_member_role'/url_for('team.change_member_role'/g" *.html

sed -i '' "s/url_for('project_report_pdf'/url_for('pdf.project_report_pdf'/g" *.html
sed -i '' "s/url_for('task_report_pdf'/url_for('pdf.task_report_pdf'/g" *.html
sed -i '' "s/url_for('employee_report_pdf'/url_for('pdf.employee_report_pdf'/g" *.html
sed -i '' "s/url_for('employee_report_view'/url_for('pdf.employee_report_view'/g" *.html

sed -i '' "s/url_for('create_folder'/url_for('files.create_folder'/g" *.html
sed -i '' "s/url_for('view_folder'/url_for('files.view_folder'/g" *.html
sed -i '' "s/url_for('delete_folder'/url_for('files.delete_folder'/g" *.html
sed -i '' "s/url_for('upload_file'/url_for('files.upload_file'/g" *.html
sed -i '' "s/url_for('download_file'/url_for('files.download_file'/g" *.html
sed -i '' "s/url_for('delete_file'/url_for('files.delete_file'/g" *.html

sed -i '' "s/url_for('send_message'/url_for('chat.send_message'/g" *.html
sed -i '' "s/url_for('mark_read'/url_for('chat.mark_read'/g" *.html

sed -i '' "s/url_for('manual_send_notifications')/url_for('admin.manual_send_notifications')/g" *.html

sed -i '' "s/url_for('create_todo'/url_for('todos.create_todo'/g" *.html
sed -i '' "s/url_for('toggle_todo'/url_for('todos.toggle_todo'/g" *.html
sed -i '' "s/url_for('update_todo_comment'/url_for('todos.update_todo_comment'/g" *.html
sed -i '' "s/url_for('delete_todo'/url_for('todos.delete_todo'/g" *.html

sed -i '' "s/url_for('create_report'/url_for('reports.create_report'/g" *.html
sed -i '' "s/url_for('delete_report'/url_for('reports.delete_report'/g" *.html

# Двойные кавычки
sed -i '' 's/url_for("events_json"/url_for("calendar.events_json"/g' *.html
sed -i '' 's/url_for("view_task"/url_for("tasks.view_task"/g' *.html
sed -i '' 's/url_for("view_project"/url_for("projects.view_project"/g' *.html
sed -i '' 's/url_for("my_calendar_json")/url_for("calendar.my_calendar_json")/g' *.html

echo "✅ PDF-шаблоны обработаны"
