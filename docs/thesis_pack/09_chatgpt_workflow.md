# 09 — How to Use ChatGPT for Writing the Thesis

## Goal
Provide ChatGPT with structured project knowledge so it can help draft accurate thesis chapters, edit language, and generate defense preparation content.

## Step 1: Build a Stable Context Set
Use the files in this folder as your master context. Start each new writing session with:
- Project summary (`01_overview.md`)
- Architecture and model (`02_architecture.md`, `03_data_model.md`)
- Feature evidence (`04_user_flows.md`, `05_business_rules.md`, `06_reports_exports.md`)

## Step 2: Add Controlled Data Samples
When needed, provide anonymized examples only:
- Export CSV from the app
- Replace personal identifiers with placeholders
- Share only the relevant subset for the chapter being drafted

## Step 3: Use Session Bootstrap Prompt
Copy this at the start of a ChatGPT session:

"You are my thesis writing assistant for a Django-based church sacramental management system. Use only the provided context files. If a detail is missing, say 'not specified'. Keep technical claims aligned with provided implementation evidence."

## Step 4: Draft by Chapter (One at a Time)
Example prompt:

"Using the attached context, draft Chapter 3 (System Design and Architecture) in 1500-2000 words with sections: introduction, architecture, data model, role-based access, request lifecycle, and conclusion."

## Step 5: Force Evidence Discipline
After each draft, run this prompt:

"List every technical claim and map it to the evidence source from the provided files. Mark any unsupported claim as 'needs verification'."

## Step 6: Improve Clarity and Defense Readiness
Use follow-up prompts:
- "Rewrite this section in simpler academic English."
- "Generate 10 viva/defense questions with model answers from this chapter."
- "Identify weak arguments and suggest stronger formulations."

## Step 7: Keep a Running Chapter Delta
After each project update, add a short change log note and feed it to ChatGPT before continuing:
- New feature
- Changed rule
- Removed behavior
- New limitation discovered

## Safety and Privacy Checklist
Before upload/share to any external AI system:
- Remove names, phone numbers, email addresses, and documents.
- Remove secrets/credentials.
- Never upload raw production databases.

## What “Teaching ChatGPT” Really Means
You are not retraining the model itself. You are supplying high-quality context per session (or via Custom GPT knowledge files), so outputs stay aligned to your project.
