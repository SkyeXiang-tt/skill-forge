"""
skill-forge/web.py
网页版 Skill Forge
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import gradio as gr

# ============ 1. 初始化 ============

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

SKILLS_DIR = "skills"
if not os.path.exists(SKILLS_DIR):
    os.makedirs(SKILLS_DIR)

current_state = {
    "sop": None,
    "sop_history": [],
    "skill": None
}


# ============ 2. SOP 生成 ============

def generate_sop(task_description, deliverable):
    if not task_description.strip():
        return "❌ 请输入任务描述", "请先填写任务描述"
    if not deliverable.strip():
        return "❌ 请输入交付要求", "请先填写交付要求"

    prompt = f"""你是一个专业的流程设计专家。请根据以下信息，生成一份详细的标准操作流程(SOP)。

## 任务描述
{task_description}

## 交付要求
{deliverable}

请以 JSON 格式输出，结构如下：
{{
    "title": "SOP标题",
    "objective": "目标概述",
    "steps": [
        {{
            "step_number": 1,
            "title": "步骤标题",
            "description": "具体做什么、怎么做",
            "input": "这一步需要什么",
            "output": "这一步产出什么",
            "acceptance_criteria": "怎么算做完了"
        }}
    ],
    "quality_checklist": ["检查项1", "检查项2"],
    "final_deliverable": "最终交付物描述"
}}

要求：
1. 步骤要细致，每一步都是可执行的
2. 上一步的 output 要能衔接下一步的 input
3. 每步都有明确的完成标准

只输出JSON，不要其他内容。"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        sop = json.loads(response.choices[0].message.content)
        current_state["sop"] = sop
        current_state["sop_history"] = []
        return format_sop(sop), "✅ SOP 生成成功！你可以修改、撤销或直接确认。"
    except Exception as e:
        return f"❌ 生成失败：{e}", "生成出错了"


# ============ 3. SOP 修改 ============

def refine_sop(feedback):
    if current_state["sop"] is None:
        return "❌ 请先生成 SOP", "请先点击「生成 SOP」"
    if not feedback.strip():
        return format_sop(current_state["sop"]), "❌ 请输入修改意见"

    prompt = f"""你之前生成了以下 SOP：

{json.dumps(current_state["sop"], ensure_ascii=False, indent=2)}

用户的反馈是：
{feedback}

请根据反馈修改 SOP，输出修改后的完整 JSON（格式不变）。
只输出 JSON，不要其他内容。"""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        new_sop = json.loads(response.choices[0].message.content)
        current_state["sop_history"].append(current_state["sop"])
        current_state["sop"] = new_sop
        version = len(current_state["sop_history"]) + 1
        return format_sop(new_sop), f"✅ SOP 已修改（当前第 {version} 版，可撤销）"
    except Exception as e:
        return f"❌ 修改失败：{e}", "修改出错了"


# ============ 4. 撤销修改 ============

def undo_sop():
    if not current_state["sop_history"]:
        if current_state["sop"]:
            return format_sop(current_state["sop"]), "⚠️ 已经是最初版本，无法再撤销"
        return "❌ 没有 SOP 可以撤销", "请先生成 SOP"

    current_state["sop"] = current_state["sop_history"].pop()
    remaining = len(current_state["sop_history"])
    return format_sop(current_state["sop"]), f"✅ 已撤销！还可以再撤销 {remaining} 次"


# ============ 5. 生成 Skill ============

def confirm_and_generate_skill():
    if current_state["sop"] is None:
        return "", "", "❌ 请先生成 SOP"

    sop = current_state["sop"]

    prompt_for_system = f"""请根据以下 SOP，为一个 AI 助手编写 system prompt。
这个 AI 助手未来会按照这个 SOP 自动执行任务。

SOP 内容：
{json.dumps(sop, ensure_ascii=False, indent=2)}

要求：
1. system prompt 要包含完整的执行流程
2. 要包含每一步的具体操作指引
3. 要包含质量检查环节
4. 要告诉 AI 以什么格式输出结果
5. 要专业、清晰、无歧义

直接输出 system prompt 文本，不要任何包装。"""

    try:
        r1 = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt_for_system}],
            temperature=0.2
        )
        system_prompt = r1.choices[0].message.content
    except Exception as e:
        return "", "", f"❌ System Prompt 生成失败：{e}"

    prompt_for_schema = f"""根据以下 SOP，定义这个工具的输入参数和输出格式。

SOP 内容：
{json.dumps(sop, ensure_ascii=False, indent=2)}

请以 JSON 格式输出：
{{
    "input_params": [
        {{
            "name": "参数名",
            "description": "参数描述",
            "type": "string",
            "required": true,
            "example": "示例值"
        }}
    ],
    "output_format": {{
        "description": "输出描述",
        "fields": [
            {{"name": "字段名", "description": "字段描述"}}
        ]
    }}
}}

只输出 JSON。"""

    try:
        r2 = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt_for_schema}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        schema = json.loads(r2.choices[0].message.content)
    except Exception as e:
        return "", "", f"❌ 输入输出定义生成失败：{e}"

    skill = {
        "skill_name": sop["title"],
        "description": sop["objective"],
        "version": "1.0",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "system_prompt": system_prompt,
        "input_params": schema.get("input_params", []),
        "output_format": schema.get("output_format", {}),
        "source_sop": sop
    }

    filename = sop["title"].replace(" ", "_").replace("/", "_")
    filepath = os.path.join(SKILLS_DIR, f"{filename}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(skill, f, ensure_ascii=False, indent=2)

    current_state["skill"] = skill

    return system_prompt, format_skill(skill), f"✅ Skill 已生成并保存到 {filepath}"


# ============ 6. 使用 Skill ============

def use_current_skill(user_input):
    if current_state["skill"] is None:
        return "❌ 请先生成 Skill，或者在「使用已有 Skill」标签页加载一个"
    if not user_input.strip():
        return "❌ 请输入内容"

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": current_state["skill"]["system_prompt"]},
                {"role": "user", "content": user_input}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ 执行失败：{e}"


# ============ 7. 加载已保存的 Skill ============

def get_saved_skills():
    skills = []
    if os.path.exists(SKILLS_DIR):
        for f in sorted(os.listdir(SKILLS_DIR)):
            if f.endswith(".json"):
                skills.append(f.replace(".json", "").replace("_", " "))
    return skills


def load_skill(skill_name):
    if not skill_name:
        return "", "", "❌ 请选择一个 Skill"

    filename = skill_name.replace(" ", "_") + ".json"
    filepath = os.path.join(SKILLS_DIR, filename)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            skill = json.load(f)
        current_state["skill"] = skill
        return skill["system_prompt"], format_skill(skill), f"✅ 已加载：{skill_name}"
    except Exception as e:
        return "", "", f"❌ 加载失败：{e}"


def refresh_skill_list():
    skills = get_saved_skills()
    if not skills:
        return gr.update(choices=[], value=None)
    return gr.update(choices=skills, value=skills[0])


# ============ 8. 格式化显示 ============

def format_sop(sop):
    text = f"# 📋 {sop['title']}\n\n"
    text += f"**🎯 目标：** {sop['objective']}\n\n---\n\n"
    text += "## 📝 步骤\n\n"
    for step in sop["steps"]:
        text += f"### 步骤 {step['step_number']}：{step['title']}\n"
        text += f"- 📖 **描述：** {step['description']}\n"
        text += f"- 📥 **输入：** {step['input']}\n"
        text += f"- 📤 **输出：** {step['output']}\n"
        text += f"- ✅ **完成标准：** {step['acceptance_criteria']}\n\n"
    text += "---\n\n## 🔍 质量检查清单\n\n"
    for item in sop["quality_checklist"]:
        text += f"- [ ] {item}\n"
    text += f"\n---\n\n**📦 最终交付物：** {sop['final_deliverable']}"
    return text


def format_skill(skill):
    text = f"# 🔧 {skill['skill_name']}\n\n"
    text += f"**📝 描述：** {skill['description']}\n\n"
    text += f"**📅 创建时间：** {skill['created_at']}\n\n"
    text += "## 📥 输入参数\n\n"
    for param in skill.get("input_params", []):
        required = "必填" if param.get("required", False) else "选填"
        text += f"- **{param['name']}** ({param.get('type', 'string')}) [{required}]\n"
        text += f"  {param.get('description', '')}\n"
        if param.get("example"):
            text += f"  示例：`{param['example']}`\n"
        text += "\n"
    text += "## 📤 输出格式\n\n"
    output = skill.get("output_format", {})
    text += f"{output.get('description', '')}\n\n"
    for field in output.get("fields", []):
        text += f"- **{field['name']}**：{field['description']}\n"
    return text


# ============ 9. 搭建网页界面 ============

with gr.Blocks(title="Skill Forge", theme=gr.themes.Soft()) as app:

    gr.Markdown("# 🔧 Skill Forge — SOP 自动生成 & Skill 固化工具")
    gr.Markdown("*输入任务描述 → AI 生成 SOP → 你确认修改 → 固化为可复用的 Skill*")
    gr.Markdown("---")

    with gr.Tabs():

        # ===== 标签页1：创建 Skill =====
        with gr.TabItem("🆕 创建新 Skill"):

            gr.Markdown("### 第一步：描述你的任务")

            with gr.Row():
                task_input = gr.Textbox(
                    label="任务描述",
                    placeholder="例如：写一篇小红书笔记",
                    lines=3
                )
                deliverable_input = gr.Textbox(
                    label="交付要求",
                    placeholder="例如：500字左右，包含标题、正文、标签，语气活泼",
                    lines=3
                )

            generate_btn = gr.Button("🚀 生成 SOP", variant="primary", size="lg")

            gr.Markdown("### 第二步：审核和修改 SOP")

            status_msg = gr.Textbox(label="状态", interactive=False)
            sop_display = gr.Markdown(label="SOP 内容")

            with gr.Row():
                feedback_input = gr.Textbox(
                    label="修改意见",
                    placeholder="例如：第三步太笼统了，请拆成更细的步骤",
                    lines=2,
                    scale=3
                )
                refine_btn = gr.Button("✏️ 修改 SOP", scale=1)
                undo_btn = gr.Button("↩️ 撤销修改", scale=1)

            gr.Markdown("### 第三步：确认并生成 Skill")

            confirm_btn = gr.Button("✅ 确认 SOP，生成 Skill", variant="primary", size="lg")

            skill_status = gr.Textbox(label="Skill 生成状态", interactive=False)
            skill_display = gr.Markdown(label="Skill 信息")

            gr.Markdown("### 第四步：复制 System Prompt 到其他平台使用")

            system_prompt_output = gr.Textbox(
                label="System Prompt（复制到 ChatGPT / Coze / Dify 使用）",
                lines=10,
                show_copy_button=True
            )

            gr.Markdown("### 第五步：在这里直接试用 Skill")

            with gr.Row():
                use_input = gr.Textbox(
                    label="输入任务参数",
                    placeholder="例如：主题是「独居女生的周末仪式感」",
                    lines=2,
                    scale=3
                )
                use_btn = gr.Button("▶️ 执行 Skill", variant="primary", scale=1)

            use_output = gr.Markdown(label="执行结果")

            # ----- 按钮事件绑定 -----

            generate_btn.click(
                fn=generate_sop,
                inputs=[task_input, deliverable_input],
                outputs=[sop_display, status_msg]
            )

            refine_btn.click(
                fn=refine_sop,
                inputs=[feedback_input],
                outputs=[sop_display, status_msg]
            )

            undo_btn.click(
                fn=undo_sop,
                inputs=[],
                outputs=[sop_display, status_msg]
            )

            confirm_btn.click(
                fn=confirm_and_generate_skill,
                inputs=[],
                outputs=[system_prompt_output, skill_display, skill_status]
            )

            use_btn.click(
                fn=use_current_skill,
                inputs=[use_input],
                outputs=[use_output]
            )

        # ===== 标签页2：使用已有 Skill =====
        with gr.TabItem("📂 使用已有 Skill"):

            gr.Markdown("### 加载之前保存的 Skill")

            with gr.Row():
                skill_dropdown = gr.Dropdown(
                    label="选择 Skill",
                    choices=get_saved_skills(),
                    scale=3
                )
                refresh_btn = gr.Button("🔄 刷新列表", scale=1)

            load_btn = gr.Button("📥 加载 Skill", variant="primary")

            load_status = gr.Textbox(label="状态", interactive=False)
            loaded_skill_display = gr.Markdown(label="Skill 信息")

            loaded_prompt_output = gr.Textbox(
                label="System Prompt（复制到其他平台使用）",
                lines=10,
                show_copy_button=True
            )

            gr.Markdown("### 使用已加载的 Skill")

            with gr.Row():
                loaded_use_input = gr.Textbox(
                    label="输入任务参数",
                    placeholder="输入你的需求...",
                    lines=2,
                    scale=3
                )
                loaded_use_btn = gr.Button("▶️ 执行 Skill", variant="primary", scale=1)

            loaded_use_output = gr.Markdown(label="执行结果")

            # ----- 按钮事件绑定 -----

            refresh_btn.click(
                fn=refresh_skill_list,
                inputs=[],
                outputs=[skill_dropdown]
            )

            load_btn.click(
                fn=load_skill,
                inputs=[skill_dropdown],
                outputs=[loaded_prompt_output, loaded_skill_display, load_status]
            )

            loaded_use_btn.click(
                fn=use_current_skill,
                inputs=[loaded_use_input],
                outputs=[loaded_use_output]
            )

# ============ 10. 启动 ============

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("🔧 Skill Forge 网页版启动中...")
    print("=" * 50)
    print("\n浏览器会自动打开，如果没有，请手动访问：")
    print("👉 http://127.0.0.1:7860")
    print("\n按 Control + C 可以停止程序")
    print("=" * 50 + "\n")

    app.launch(share=False)

