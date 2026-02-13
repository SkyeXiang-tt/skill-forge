"""
skill-forge/web.py
"""
import os, io, json, base64, re
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import streamlit as st

load_dotenv()
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    try:
        api_key = st.secrets["DEEPSEEK_API_KEY"]
    except Exception:
        st.error("请配置 DEEPSEEK_API_KEY")
        st.stop()

client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
SKILLS_DIR = "skills"
OUTPUT_DIR = "outputs"
os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

for key, val in [("sop", None), ("sop_history", []), ("skill", None), ("chat_history", []), ("uploaded_text", "")]:
    if key not in st.session_state:
        st.session_state[key] = val

UPLOAD_TYPES = ["txt","pdf","docx","xlsx","csv","json","md","pptx","xls","png","jpg","jpeg","gif","bmp","webp"]
OUTPUT_OPTIONS = ["纯文字（不生成文件）","Word (.docx)","Excel (.xlsx)","PPT (.pptx)","TXT (.txt)","Markdown (.md)","JSON (.json)","PNG (.png)","JPG (.jpg)"]
FMT_MAP = {"Word (.docx)":"docx","Excel (.xlsx)":"xlsx","PPT (.pptx)":"pptx","TXT (.txt)":"txt","Markdown (.md)":"md","JSON (.json)":"json","PNG (.png)":"png","JPG (.jpg)":"jpg"}

def read_uploaded_file(uploaded_file):
    name = uploaded_file.name.lower()
    try:
        if name.endswith((".png",".jpg",".jpeg",".gif",".bmp",".webp")):
            img_bytes = uploaded_file.read()
            return f"[图片文件: {uploaded_file.name}, 大小: {len(img_bytes)/1024:.1f}KB]"
        elif name.endswith((".txt",".md")):
            return uploaded_file.read().decode("utf-8")
        elif name.endswith(".json"):
            return json.dumps(json.loads(uploaded_file.read().decode("utf-8")), ensure_ascii=False, indent=2)
        elif name.endswith(".csv"):
            return uploaded_file.read().decode("utf-8")
        elif name.endswith(".docx"):
            from docx import Document
            return "\n".join([p.text for p in Document(uploaded_file).paragraphs if p.text.strip()])
        elif name.endswith((".xlsx",".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(uploaded_file)
            text = ""
            for s in wb.sheetnames:
                ws = wb[s]
                text += f"\n--- {s} ---\n"
                for row in ws.iter_rows(values_only=True):
                    text += " | ".join([str(c) if c else "" for c in row]) + "\n"
            return text
        elif name.endswith(".pptx"):
            from pptx import Presentation
            prs = Presentation(uploaded_file)
            text = ""
            for i, slide in enumerate(prs.slides):
                text += f"\n--- 幻灯片 {i+1} ---\n"
                for shape in slide.shapes:
                    if hasattr(shape,"text") and shape.text.strip():
                        text += shape.text + "\n"
            return text
        elif name.endswith(".pdf"):
            import PyPDF2
            reader = PyPDF2.PdfReader(uploaded_file)
            return "\n".join([p.extract_text() for p in reader.pages])
        else:
            return uploaded_file.read().decode("utf-8")
    except Exception as e:
        return f"[读取失败: {e}]"

def generate_txt(content, fn):
    return content.encode("utf-8"), f"{fn}.txt", "text/plain"

def generate_word(content, fn):
    from docx import Document
    doc = Document()
    for line in content.split("\n"):
        line = line.strip()
        if not line: continue
        if line.startswith("# "): doc.add_heading(line[2:], level=1)
        elif line.startswith("## "): doc.add_heading(line[3:], level=2)
        elif line.startswith("### "): doc.add_heading(line[4:], level=3)
        else: doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue(), f"{fn}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

def generate_excel(content, fn):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for ri, line in enumerate(content.strip().split("\n"), 1):
        line = line.strip().strip("|")
        if not line: continue
        for ci, cell in enumerate([c.strip() for c in line.split("|")], 1):
            if cell.replace("-","").strip(): ws.cell(row=ri, column=ci, value=cell)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue(), f"{fn}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

def generate_ppt(content, fn):
    from pptx import Presentation
    prs = Presentation()
    parts = content.split("---")
    if len(parts) == 1: parts = content.split("\n\n")
    for part in parts:
        part = part.strip()
        if not part: continue
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        lines = part.split("\n")
        slide.shapes.title.text = lines[0].lstrip("#").strip() if lines else "幻灯片"
        if len(lines) > 1 and slide.placeholders[1]:
            slide.placeholders[1].text = "\n".join(lines[1:]).strip()
    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf.getvalue(), f"{fn}.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"

def generate_image(content, fn, fmt="png"):
    from PIL import Image, ImageDraw
    lines = content.split("\n")
    wrapped = []
    for l in lines:
        while len(l) > 70:
            wrapped.append(l[:70])
            l = l[70:]
        wrapped.append(l)
    h = max(600, len(wrapped)*28+80)
    img = Image.new("RGB", (900, h), "white")
    draw = ImageDraw.Draw(img)
    y = 30
    for l in wrapped:
        draw.text((30, y), l, fill="black")
        y += 28
    buf = io.BytesIO()
    img.save(buf, format="PNG" if fmt=="png" else "JPEG")
    buf.seek(0)
    return buf.getvalue(), f"{fn}.{fmt}", f"image/{fmt}" if fmt=="png" else "image/jpeg"

def auto_generate_file(content, output_format, skill_name):
    fn = skill_name.replace(" ","_").replace("/","_") + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    fmt = output_format.lower().strip()
    if fmt in ["word","docx"]: return generate_word(content, fn)
    elif fmt in ["excel","xlsx"]: return generate_excel(content, fn)
    elif fmt in ["ppt","pptx"]: return generate_ppt(content, fn)
    elif fmt in ["txt","text"]: return generate_txt(content, fn)
    elif fmt == "json": return content.encode("utf-8"), f"{fn}.json", "application/json"
    elif fmt in ["md","markdown"]: return content.encode("utf-8"), f"{fn}.md", "text/markdown"
    elif fmt == "png": return generate_image(content, fn, "png")
    elif fmt in ["jpg","jpeg"]: return generate_image(content, fn, "jpg")
    else: return generate_txt(content, fn)

def call_generate_sop(task_description, deliverable):
    prompt = f"""你是一个专业的流程设计专家。请根据以下信息，生成一份详细的标准操作流程(SOP)。

## 任务描述
{task_description}

## 交付要求
{deliverable}

请以 JSON 格式输出：
{{"title":"SOP标题","objective":"目标概述","steps":[{{"step_number":1,"title":"步骤标题","description":"具体做什么","input":"需要什么","output":"产出什么","acceptance_criteria":"完成标准"}}],"quality_checklist":["检查项1"],"final_deliverable":"最终交付物"}}

只输出JSON。"""
    response = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user","content":prompt}], temperature=0.3, response_format={"type":"json_object"})
    return json.loads(response.choices[0].message.content)

def call_refine_sop(current_sop, feedback):
    prompt = f"""你之前生成了以下 SOP：
{json.dumps(current_sop, ensure_ascii=False, indent=2)}
用户反馈：{feedback}
请修改 SOP，输出完整 JSON（格式不变）。只输出 JSON。"""
    response = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user","content":prompt}], temperature=0.3, response_format={"type":"json_object"})
    return json.loads(response.choices[0].message.content)

def call_generate_skill(sop):
    p1 = f"""请根据以下 SOP 为 AI 助手编写 system prompt。
SOP：{json.dumps(sop, ensure_ascii=False, indent=2)}
要求：包含完整执行流程、操作指引、质量检查、输出格式。直接输出 system prompt。"""
    r1 = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user","content":p1}], temperature=0.2)
    system_prompt = r1.choices[0].message.content
    p2 = f"""根据以下 SOP 定义输入参数和输出格式。
SOP：{json.dumps(sop, ensure_ascii=False, indent=2)}
以 JSON 输出：{{"input_params":[{{"name":"参数名","description":"描述","type":"string","required":true,"example":"示例"}}],"output_format":{{"description":"输出描述","fields":[{{"name":"字段名","description":"描述"}}]}}}}
只输出 JSON。"""
    r2 = client.chat.completions.create(model="deepseek-chat", messages=[{"role":"user","content":p2}], temperature=0.2, response_format={"type":"json_object"})
    schema = json.loads(r2.choices[0].message.content)
    return {"skill_name":sop["title"],"description":sop["objective"],"version":"1.0","created_at":datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"system_prompt":system_prompt,"input_params":schema.get("input_params",[]),"output_format":schema.get("output_format",{}),"source_sop":sop}

def display_sop(sop):
    st.markdown(f"## 📋 {sop['title']}")
    st.markdown(f"**🎯 目标：** {sop['objective']}")
    st.markdown("---")
    for step in sop["steps"]:
        st.markdown(f"### 步骤 {step['step_number']}：{step['title']}")
        st.markdown(f"- 📖 **描述：** {step['description']}")
        st.markdown(f"- 📥 **输入：** {step['input']}")
        st.markdown(f"- 📤 **输出：** {step['output']}")
        st.markdown(f"- ✅ **完成标准：** {step['acceptance_criteria']}")
    st.markdown("---")
    st.markdown("### 🔍 质量检查清单")
    for item in sop["quality_checklist"]:
        st.markdown(f"- {item}")
    st.markdown(f"**📦 最终交付物：** {sop['final_deliverable']}")

st.set_page_config(page_title="Skill Forge", page_icon="🔧", layout="wide")
st.title("🔧 Skill Forge")
st.markdown("*输入任务描述 → AI 生成 SOP → 你确认修改 → 固化为可复用的 Skill*")
st.markdown("---")
tab1, tab2 = st.tabs(["🆕 创建新 Skill", "📂 使用已有 Skill"])

with tab1:
    st.markdown("### 第一步：描述你的任务")
    c1, c2 = st.columns(2)
    with c1:
        task_desc = st.text_area("任务描述", placeholder="例如：写一篇小红书笔记", height=100)
    with c2:
        deliverable = st.text_area("交付要求", placeholder="例如：500字左右，包含标题、正文、标签", height=100)
    st.markdown("### 📎 上传参考文件（可选）")
    uploaded_files = st.file_uploader("支持多种格式", accept_multiple_files=True, type=UPLOAD_TYPES)
    if uploaded_files:
        all_text = ""
        for uf in uploaded_files:
            st.markdown(f"✅ 已上传：**{uf.name}**")
            all_text += f"\n\n=== {uf.name} ===\n{read_uploaded_file(uf)}"
        st.session_state.uploaded_text = all_text
        with st.expander("📄 查看文件内容"):
            st.text(all_text[:3000] + ("..." if len(all_text) > 3000 else ""))
    if st.button("🚀 生成 SOP", type="primary", use_container_width=True):
        if not task_desc.strip() or not deliverable.strip():
            st.error("请填写任务描述和交付要求")
        else:
            full_task = task_desc
            if st.session_state.uploaded_text:
                full_task += f"\n\n## 参考资料\n{st.session_state.uploaded_text}"
            with st.spinner("正在生成 SOP..."):
                try:
                    sop = call_generate_sop(full_task, deliverable)
                    st.session_state.sop = sop
                    st.session_state.sop_history = []
                    st.success("SOP 生成成功！")
                    st.rerun()
                except Exception as e:
                    st.error(f"生成失败：{e}")
    if st.session_state.sop is not None:
        st.markdown("---")
        st.markdown("### 第二步：审核和修改 SOP")
        display_sop(st.session_state.sop)
        st.markdown("---")
        feedback = st.text_input("修改意见", placeholder="例如：第三步太笼统了，请拆成更细的步骤")
        ca, cb = st.columns(2)
        with ca:
            if st.button("✏️ 提交修改", use_container_width=True):
                if not feedback.strip():
                    st.warning("请输入修改意见")
                else:
                    with st.spinner("正在修改 SOP..."):
                        try:
                            st.session_state.sop_history.append(st.session_state.sop)
                            st.session_state.sop = call_refine_sop(st.session_state.sop, feedback)
                            st.success("修改成功！")
                            st.rerun()
                        except Exception as e:
                            st.session_state.sop_history.pop()
                            st.error(f"修改失败：{e}")
        with cb:
            if st.button("↩️ 撤销修改", use_container_width=True):
                if not st.session_state.sop_history:
                    st.warning("已经是最初版本")
                else:
                    st.session_state.sop = st.session_state.sop_history.pop()
                    st.success("已撤销！")
                    st.rerun()
        st.markdown("---")
        st.markdown("### 第三步：确认并生成 Skill")
        if st.button("✅ 确认 SOP，生成 Skill", type="primary", use_container_width=True):
            with st.spinner("正在生成 Skill（约需30秒）..."):
                try:
                    skill = call_generate_skill(st.session_state.sop)
                    fn = skill["skill_name"].replace(" ","_").replace("/","_")
                    fp = os.path.join(SKILLS_DIR, f"{fn}.json")
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(skill, f, ensure_ascii=False, indent=2)
                    st.session_state.skill = skill
                    st.session_state.chat_history = []
                    st.success(f"Skill 已生成！")
                    st.rerun()
                except Exception as e:
                    st.error(f"生成失败：{e}")
    if st.session_state.skill is not None:
        st.markdown("---")
        st.markdown("### 第四步：复制 System Prompt")
        st.text_area("System Prompt", value=st.session_state.skill["system_prompt"], height=200, key="pc1")
        st.markdown("---")
        st.markdown("### 第五步：多轮对话试用 Skill")
        chat_files = st.file_uploader("📎 上传文件（可选）", accept_multiple_files=True, type=UPLOAD_TYPES, key="cf1")
        cft = ""
        if chat_files:
            for cf in chat_files:
                st.markdown(f"✅ {cf.name}")
                cft += f"\n\n=== {cf.name} ===\n{read_uploaded_file(cf)}"
        ofmt = st.selectbox("📤 输出格式", OUTPUT_OPTIONS, key="of1")
        for msg in st.session_state.chat_history:
            st.chat_message(msg["role"]).markdown(msg["content"])
        user_msg = st.chat_input("输入你的内容")
        if user_msg:
            full_msg = user_msg
            if cft:
                full_msg += f"\n\n## 参考文件\n{cft}"
            st.session_state.chat_history.append({"role":"user","content":full_msg})
            st.chat_message("user").markdown(user_msg)
            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    try:
                        msgs = [{"role":"system","content":st.session_state.skill["system_prompt"]}]
                        msgs.extend(st.session_state.chat_history)
                        response = client.chat.completions.create(model="deepseek-chat", messages=msgs, temperature=0.3)
                        reply = response.choices[0].message.content
                        st.markdown(reply)
                        st.session_state.chat_history.append({"role":"assistant","content":reply})
                        if ofmt != "纯文字（不生成文件）":
                            fmt = FMT_MAP.get(ofmt, "txt")
                            fd, ffn, mt = auto_generate_file(reply, fmt, st.session_state.skill["skill_name"])
                            st.download_button(f"📥 下载 {ffn}", data=fd, file_name=ffn, mime=mt)
                    except Exception as e:
                        st.error(f"执行失败：{e}")
        if st.session_state.chat_history:
            if st.button("🗑️ 清空对话", key="cl1"):
                st.session_state.chat_history = []
                st.rerun()

with tab2:
    st.markdown("### 加载已有 Skill")
    skill_files = []
    if os.path.exists(SKILLS_DIR):
        skill_files = [f.replace(".json","").replace("_"," ") for f in sorted(os.listdir(SKILLS_DIR)) if f.endswith(".json")]
    if not skill_files:
        st.info("还没有 Skill，请先创建一个")
    else:
        selected = st.selectbox("选择 Skill", skill_files)
        if st.button("📥 加载 Skill", type="primary"):
            fp = os.path.join(SKILLS_DIR, selected.replace(" ","_")+".json")
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    skill = json.load(f)
                st.session_state.skill = skill
                st.session_state.chat_history = []
                st.success(f"已加载：{selected}")
                st.rerun()
            except Exception as e:
                st.error(f"加载失败：{e}")
        if st.session_state.skill is not None:
            st.markdown("---")
            st.markdown(f"**当前 Skill：** {st.session_state.skill['skill_name']}")
            st.text_area("System Prompt", value=st.session_state.skill["system_prompt"], height=200, key="pc2")
            st.markdown("---")
            st.markdown("### 多轮对话")
            chat_files2 = st.file_uploader("📎 上传文件（可选）", accept_multiple_files=True, type=UPLOAD_TYPES, key="cf2")
            cft2 = ""
            if chat_files2:
                for cf in chat_files2:
                    st.markdown(f"✅ {cf.name}")
                    cft2 += f"\n\n=== {cf.name} ===\n{read_uploaded_file(cf)}"
            ofmt2 = st.selectbox("📤 输出格式", OUTPUT_OPTIONS, key="of2")
            for msg in st.session_state.chat_history:
                st.chat_message(msg["role"]).markdown(msg["content"])
            user_msg2 = st.chat_input("输入你的需求...", key="ci2")
            if user_msg2:
                full_msg2 = user_msg2
                if cft2:
                    full_msg2 += f"\n\n## 参考文件\n{cft2}"
                st.session_state.chat_history.append({"role":"user","content":full_msg2})
                st.chat_message("user").markdown(user_msg2)
                with st.chat_message("assistant"):
                    with st.spinner("思考中..."):
                        try:
                            msgs = [{"role":"system","content":st.session_state.skill["system_prompt"]}]
                            msgs.extend(st.session_state.chat_history)
                            response = client.chat.completions.create(model="deepseek-chat", messages=msgs, temperature=0.3)
                            reply = response.choices[0].message.content
                            st.markdown(reply)
                            st.session_state.chat_history.append({"role":"assistant","content":reply})
                            if ofmt2 != "纯文字（不生成文件）":
                                fmt = FMT_MAP.get(ofmt2, "txt")
                                fd, ffn, mt = auto_generate_file(reply, fmt, st.session_state.skill["skill_name"])
                                st.download_button(f"📥 下载 {ffn}", data=fd, file_name=ffn, mime=mt, key=f"dl_{ffn}")
                        except Exception as e:
                            st.error(f"执行失败：{e}")
            if st.session_state.chat_history:
                if st.button("🗑️ 清空对话", key="cl2"):
                    st.session_state.chat_history = []
                    st.rerun()

