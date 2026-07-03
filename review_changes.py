import os

files_to_review = [
    'requirements.txt',
    'gtk_llm_chat/main.py',
    'gtk_llm_chat/platform_utils.py',
    'gtk_llm_chat/welcome.py',
    'gtk_llm_chat/chat_application.py',
    'gtk_llm_chat/llm_conversation_sidebar.py',
    'gtk_llm_chat/chat_window.py'
]

for file_path in files_to_review:
    print(f"--- {file_path} ---")
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            print(f.read())
    else:
        print("FILE DELETED")
    print("\n" + "="*40 + "\n")
