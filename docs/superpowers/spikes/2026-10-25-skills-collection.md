# Spike: abubakarsiddik31/claude-skills-collection

Repo commit `be1b892dda5e43ae8589203a91c38b93998883c8` (cloned 2026-10-25, depth 1).

## Recommendation

- **The repo itself ships no skills.** It is one file, `README.md`: an index of 252 links to other repos. Nothing in it can be installed or run, and its licence note says each linked repo has its own terms.
- **Adopt (optional, install from the source repos, not from this one):** `antonbabenko/terraform-skill` (Apache-2.0). It is the only candidate that fills a real gap: no Terraform skill is installed, and the user works in Terraform on GCP.
- **Maybe:** `terraform-test` and `terraform-style-guide` from `hashicorp/agent-skills` (MPL-2.0, no scripts). Take them only if `terraform-skill` leaves test and style gaps.
- **Skip the rest.** About 175 of the 252 have no installed counterpart, but they are off-domain: mobile, Cloudflare, Stripe, academic, resumes and so on. Most of the other 77 duplicate superpowers skills already installed.
- **Skip `cc-devops-skills`' `gitlab-ci-validator`** for now. It is useful but has a pip/npm installer and `gitlab-ci-local` needs Docker. `gitlab-ci-loop` is already installed.

## Inventory

Count: **252** skills, taken from the 252 `| **name** |` table rows in `README.md` (`grep -cE '^\| \*\*'` gives 252). The README's own overview also says 252. The table below has 252 numbered rows (checked with `grep -c '^| [0-9]'`). "Overlap" is judged from the name and the README description only, because the skill bodies live in other repos. "(partial)" means partly overlapping. "plugin" means a skill found under `~/.claude/plugins/`.

| # | Name | What it does | Overlap with installed skill |
|---|------|--------------|------------------------------|
| 1 | docx | Create and edit Microsoft Word documents with formatting, comments, and tracked changes | none |
| 2 | pdf | Extract content from PDFs, split/merge documents, or create new ones | anthropic-skills:pdf |
| 3 | pptx | Generate and edit PowerPoint presentations | anthropic-skills:pptx |
| 4 | xlsx | Manipulate Excel files, formulas, tables, and charts | none |
| 5 | revealjs-skill | Generate polished, professional presentations using the Reveal.js HTML presentation framework | anthropic-skills:pptx (partial) |
| 6 | algorithmic-art | Create generative art using p5.js | none |
| 7 | canvas-design | Render layout-based visual designs in PNG/PDF | none |
| 8 | slack-gif-creator | Generate Slack-optimized animated GIFs | none |
| 9 | brand-guidelines | Apply company branding to outputs | none |
| 10 | theme-factory | Create and apply visual themes for documents | none |
| 11 | nano-banana-image-generation | Create images using Nano Banana Pro | none |
| 12 | frontend-slides | Create animation-rich single-file HTML presentations with 12 visual styles and zero dependencies | anthropic-skills:pptx (partial) |
| 13 | web-asset-generator | Generate favicons, app icons, PWA manifests, and Open Graph images with WCAG contrast validation | none |
| 14 | color-expert | Color science and accessibility expertise covering APCA/WCAG, palette systems, and color-space decisions | dataviz (partial) |
| 15 | design-mobile-apps | Design mobile app UI screens and implement Sleek designs in HTML, React Native, or SwiftUI | none |
| 16 | frontend-design | Official Anthropic guidance for distinctive, intentional visual design — aesthetic direction, typography, and av... | frontend-design (plugin) |
| 17 | web-design-guidelines | Official Vercel skill that reviews UI code against Web Interface Guidelines for accessibility, interaction, and... | none |
| 18 | emil-design-eng | Emil Kowalski's design-engineering philosophy: UI polish, component design, animation decisions, and the invisib... | none |
| 19 | code-review | Two-axis review of changes since a fixed point — Standards (coding standards) and Spec (originating issue/PRD) —... | code-review |
| 20 | claude-api | Official Anthropic guidance for building, debugging, and optimizing Claude API applications, including tool use,... | claude-api |
| 21 | claude-skills-pro | 15 engineering-workflow skills (7-dimension code review, root-cause bug hunting, test generation with mutation c... | superpowers-extended-cc:systematic-debugging; code-review (partial) |
| 22 | codebase-design | Shared vocabulary for designing deep modules — lots of behaviour behind a small interface at a clean seam | architecture (plugin) (partial) |
| 23 | diagnosing-bugs | Disciplined diagnosis loop for hard bugs and performance regressions: reproduce, minimize, hypothesize, instrume... | superpowers-extended-cc:systematic-debugging |
| 24 | domain-modeling | Build and sharpen a project's domain model with ubiquitous language, glossary entries, and architectural decisio... | architecture (plugin) (partial) |
| 25 | grill-with-docs | Grilling workflow that pressure-tests plans against domain language and updates CONTEXT.md and ADRs | superpowers-extended-cc:brainstorming (partial) |
| 26 | implement | Implement a piece of work based on a spec or set of tickets, driving TDD internally per issue | superpowers-extended-cc:executing-plans |
| 27 | improve-codebase-architecture | Find deepening opportunities in a codebase using shared domain language and architectural decisions | architecture (plugin) (partial) |
| 28 | prototype | Build throwaway prototypes for logic or UI exploration before production implementation | playground (plugin) (partial) |
| 29 | research | Delegate reading legwork to a background agent that investigates against primary sources and leaves a cited Mark... | anthropic-skills:deep-research |
| 30 | resolving-merge-conflicts | Resolve in-progress git merge/rebase conflicts by understanding both changes' intent and preserving it | fix-merge-conflicts |
| 31 | setup-matt-pocock-skills | One-time repository setup for issue tracker, triage labels, and docs layout used by the engineering skill suite | none |
| 32 | tdd | Test-driven development workflow using a red-green-refactor loop and vertical slices | superpowers-extended-cc:test-driven-development |
| 33 | to-spec | Turn the current conversation into a spec and publish it to the project issue tracker — synthesis, no interview | superpowers-extended-cc:brainstorming (partial) |
| 34 | to-tickets | Break a plan, spec, or conversation into tracer-bullet tickets, each declaring its blocking edges | superpowers-extended-cc:writing-plans |
| 35 | triage | Triage work through a structured issue-state workflow with explicit roles | none |
| 36 | wayfinder | Plan huge multi-session work as a shared map of investigation tickets, resolving them one at a time until the ro... | superpowers-extended-cc:writing-plans (partial) |
| 37 | interview-me | Interactive requirements interview loop to uncover hidden assumptions before implementation | superpowers-extended-cc:brainstorming (partial) |
| 38 | source-driven-development | Ground implementation in primary sources and existing code reality before writing changes | none |
| 39 | performance-optimization | Diagnose and improve runtime, render, and bundle performance with systematic profiling | none |
| 40 | code-review-and-quality | Enforce production-grade review criteria, maintainability, and quality gates | code-review |
| 41 | incremental-implementation | Ship complex features as small validated slices to reduce risk and regressions | superpowers-extended-cc:executing-plans |
| 42 | planning-and-task-breakdown | Convert broad goals into sequenced, executable engineering tasks | superpowers-extended-cc:writing-plans |
| 43 | swiftui-pro | Advanced SwiftUI development patterns and implementation guidance for Apple platforms | none |
| 44 | swift-concurrency-pro | Practical Swift Concurrency patterns for structured async code and correctness | none |
| 45 | react-components-stitch | Generate robust React components using Stitch-oriented implementation patterns | none |
| 46 | MCP Server | Build Claude-compatible API connectors | build-mcp-server (plugin) |
| 47 | Changelog Generator | Create changelogs from commit history | none |
| 48 | using-git-worktrees | Manage feature branches safely in isolated Git worktrees | superpowers-extended-cc:using-git-worktrees |
| 49 | test-driven-development | Write tests before implementation to drive development | superpowers-extended-cc:test-driven-development |
| 50 | subagent-driven-development | Use multiple Claude subagents to coordinate complex implementations | superpowers-extended-cc:subagent-driven-development |
| 51 | executing-plans | Execute structured plans with checkpoints and verification steps | superpowers-extended-cc:executing-plans |
| 52 | finishing-a-development-branch | Complete development branches with testing and review flow | superpowers-extended-cc:finishing-a-development-branch |
| 53 | preserving-productive-tensions | Manage architectural decisions by preserving competing viewpoints to balance innovation and stability | none |
| 54 | web-artifacts-builder | Create elaborate, multi-component claude.ai HTML artifacts using modern frontend web technologies (React, Tailwi... | artifact-design (partial) |
| 55 | pypict-claude-skill | Design comprehensive test cases using PICT (Pairwise Independent Combinatorial Testing) for optimized test suites | none |
| 56 | aws-skills | AWS development with CDK best practices, cost optimization, and serverless/event-driven architecture patterns | none |
| 57 | move-code-quality-skill | Analyzes Move language packages against the official Move Book Code Quality Checklist | none |
| 58 | audit-website | Cli website auditing tool for seo, performance, security and 140+ other rules | none |
| 59 | stripe-best-practices | Official Stripe skill for building correct integrations with payments, subscriptions, and webhooks | none |
| 60 | upgrade-stripe | Official Stripe skill for safely upgrading SDK and API versions | none |
| 61 | expo-app-design | Official Expo skill for designing and building Expo/React Native apps with best practices | none |
| 62 | supabase-postgres | Official Supabase skill for PostgreSQL best practices in Supabase projects | none |
| 63 | terraform-code-generation | Official HashiCorp skill for generating and validating Terraform HCL code | none |
| 64 | terraform-module-generation | Official HashiCorp skill for creating and refactoring Terraform modules | none |
| 65 | terraform-provider-development | Official HashiCorp skill for developing custom Terraform providers | none |
| 66 | terraform-skill | Comprehensive Terraform/OpenTofu best practices covering testing, modules, CI/CD, and 100+ patterns | none |
| 67 | cloudflare-agents-sdk | Official Cloudflare skill for building stateful AI agents with scheduling, RPC, and MCP on Workers | none |
| 68 | cloudflare-wrangler | Official Cloudflare skill for deploying and managing Workers, KV, R2, D1, and Queues | none |
| 69 | cloudflare-web-perf | Official Cloudflare skill for auditing Core Web Vitals and render-blocking resources | none |
| 70 | cloudflare-building-ai-agent | Official Cloudflare skill for building full AI agents on Cloudflare's infrastructure | none |
| 71 | cloudflare-building-mcp-server | Official Cloudflare skill for building and deploying MCP servers on Cloudflare Workers | none |
| 72 | cloudflare-durable-objects | Official Cloudflare skill for building stateful, globally consistent applications with Durable Objects | none |
| 73 | cloudflare-sandbox-sdk | Official Cloudflare skill for running untrusted code safely using Cloudflare's sandbox environment | none |
| 74 | cloudflare-workers-best-practices | Official Cloudflare skill for Workers best practices covering performance, security, and deployment patterns | none |
| 75 | netlify-functions | Official Netlify skill for building serverless API endpoints and background tasks | none |
| 76 | netlify-db | Official Netlify skill for managed Postgres with deploy preview branching | none |
| 77 | neon-postgres | Official Neon skill for best practices with Neon Serverless Postgres | none |
| 78 | vercel-react | Official Vercel skill for React best practices and patterns | none |
| 79 | next-best-practices | Official Vercel skill for Next.js recommended patterns and best practices | none |
| 80 | next-upgrade | Official Vercel skill for upgrading Next.js projects to newer versions | none |
| 81 | react-native-best-practices | Official Callstack skill for React Native performance optimization patterns | none |
| 82 | better-auth | Official Better Auth skill for authentication integration including OAuth, 2FA, and passkeys | none |
| 83 | tinybird | Official Tinybird skill for project guidelines covering datasources, pipes, endpoints, and SQL | none |
| 84 | sanity | Official Sanity skill for Sanity Studio, GROQ queries, and content workflows | none |
| 85 | clickhouse | Official ClickHouse skill for analytics query best practices | none |
| 86 | remotion-skill | Official Remotion skill for programmatic video creation with React | none |
| 87 | ios-simulator-skill | 21-script toolkit for iOS simulator automation with accessibility APIs and 96% token reduction | none |
| 88 | claude-d3js-skill | Interactive data visualizations using D3.js with reference materials and patterns | dataviz |
| 89 | playwright-skill | General-purpose browser automation with Playwright for testing and web interaction | claude-in-chrome (partial) |
| 90 | claude-a11y-skill | Comprehensive accessibility audits combining axe-core and eslint-plugin-jsx-a11y against WCAG 2.1 | accessibility-review (plugin) |
| 91 | context-engineering-kit | Advanced context engineering with multi-agent patterns, reflexion loops, and domain-driven development | superpowers-extended-cc:subagent-driven-development (partial) |
| 92 | compound-engineering-plugin | Pragmatic engineering plugin with ideation, planning, execution, multi-agent review, and knowledge compounding | superpowers-extended-cc:brainstorming; writing-plans (partial) |
| 93 | vscode-extension-builder | Scaffolds, compiles, packages, and installs a working VS Code extension end-to-end from a single request — comma... | none |
| 94 | ponytail | Forces the laziest solution that actually works — YAGNI, standard library before custom code, one line before fi... | none |
| 95 | agent-browser | Official Vercel browser automation CLI for AI agents — navigate pages, fill forms, click, screenshot, extract da... | claude-in-chrome (partial) |
| 96 | prisma-client-api | Official Prisma reference for Client API queries, filters, operators, transactions, and client configuration | none |
| 97 | google-agents-cli-deploy | Official Google skill for deploying ADK agents to Agent Runtime, Cloud Run, or GKE, with CI/CD, secrets, and Age... | none |
| 98 | microsoft-foundry | Official Microsoft skill for building, deploying, evaluating, and managing Foundry agents, models, and resources... | none |
| 99 | prompt-engineer | Turns a request into a production-ready prompt with test cases and success criteria, and routes to a hook, skill... | none |
| 100 | orca-replay | Answers questions about a past agent run from its recording rather than from memory — what it sent, ran and chan... | none |
| 101 | csv-data-summarizer | Generate statistics and charts from CSVs | dataviz (partial) |
| 102 | root-cause-tracing | Trace and diagnose the source of data or logic errors | superpowers-extended-cc:systematic-debugging |
| 103 | postgres | Execute safe read-only SQL queries against PostgreSQL databases with multi-connection support | none |
| 104 | read-only-postgres | Safe read-only PostgreSQL queries with multi-connection support and defense-in-depth security | none |
| 105 | prompt-template-wizard | Converts incomplete feature/bug requests into complete structured prompt templates | none |
| 106 | monte-carlo-agent-toolkit | Official data and agent observability skills for monitoring, triage, troubleshooting, and health checks | none |
| 107 | claude-scientific-skills | 125+ scientific skills for bioinformatics, cheminformatics, clinical research, and machine learning | none |
| 108 | materials-simulation-skills | Agent skills for computational materials science: numerical stability, time-stepping, linear solvers, and simula... | none |
| 109 | extract-from-pdfs | Extract structured data from scientific PDFs using Claude's vision with external validation against GBIF/WFO dat... | none |
| 110 | phylo-from-buscos | Phylogenomic workflows from genome assemblies using BUSCO single-copy orthologs | none |
| 111 | claude-mountaineering-skills | Mountain route research aggregating 10+ sources including weather, avalanche forecasts, and hazard analysis | none |
| 112 | article-extractor | Extract full content from web articles | none |
| 113 | Content Research Writer | Research and refine written content with feedback | none |
| 114 | internal-comms | Draft formal internal comms and reports | none |
| 115 | writing-plans | Create structured written plans with clear milestones | superpowers-extended-cc:writing-plans |
| 116 | writing-skills | Enhance instructional and technical writing quality | superpowers-extended-cc:writing-skills |
| 117 | brainstorming | Facilitate creative idea generation sessions | superpowers-extended-cc:brainstorming |
| 118 | family-history-research | Provides assistance with planning family history and genealogy research projects | none |
| 119 | avoid-ai-writing | Audit and rewrite content to remove 21 categories of AI writing patterns with a 43-entry replacement table | none |
| 120 | non-fiction-book-factory | Complete nonfiction book creation pipeline replicating traditional publishing infrastructure | none |
| 121 | ebook-factory | Focused ebook creation pipeline for producing publication-ready digital books | none |
| 122 | academic-research-skills | 13-agent pipeline for rigorous academic research with Socratic guided mode and systematic review/PRISMA support | none |
| 123 | academic-paper | 12-agent paper writing system with LaTeX output, visualization generation, revision coaching, and multi-format c... | none |
| 124 | academic-paper-reviewer | Multi-perspective peer review with 0-100 quality rubrics, Editor-in-Chief, 3 dynamic reviewers, and Devil's Advo... | none |
| 125 | claude-scientific-writer | Publication-ready scientific document generation with real-time research lookup, citation management, and 8-dime... | none |
| 126 | claude-blog | Blog content creation ecosystem with 12 commands for writing, rewriting, SEO, schema markup, content repurposing... | none |
| 127 | claude-email | AI-powered email management with inbox triage, composition using copywriting frameworks (PAS, AIDA, BAB), delive... | none |
| 128 | autoresearch | Autonomous research orchestration using a two-loop architecture managing the full lifecycle from literature surv... | anthropic-skills:deep-research (partial) |
| 129 | writing-fragments | Mine raw fragments through relentless grilling — pure explore mode with no structure imposed | none |
| 130 | writing-beats | Assemble raw material into a journey of beats, grounding each term before a beat leans on it | none |
| 131 | writing-shape | Shape raw material into an article, paragraph by paragraph, from a pile of notes or fragments | none |
| 132 | humanizer | Rewrites AI-sounding text so it reads like a person wrote it, without changing what it says — based on Wikipedia... | none |
| 133 | no-ai-slop | Edits drafts into sharper, more human writing while preserving the writer's personal voice, removing 20+ pattern... | none |
| 134 | tapestry | Build a linked knowledge graph from documents | research-synthesis (plugin) (partial) |
| 135 | ship-learn-next | Recommend next steps based on feedback loops | retro (~/.claude/skills) (partial) |
| 136 | using-superpowers | Learn and apply best practices for Superpowers workflows | superpowers-extended-cc:using-superpowers |
| 137 | sharing-skills | Learn how to contribute new skills via pull requests | anthropic-skills:skill-creator (partial) |
| 138 | collision-zone-thinking | Combine unrelated concepts to find new creative or problem-solving connections | none |
| 139 | inversion-exercise | Flip assumptions to uncover hidden insights and constraints | none |
| 140 | meta-pattern-recognition | Identify patterns across domains to uncover universal principles | none |
| 141 | scale-game | Stress-test ideas at extreme scales to expose hidden weaknesses or truths | none |
| 142 | simplification-cascades | Reduce complexity by discovering insights that simplify multiple elements at once | none |
| 143 | tracing-knowledge-lineages | Track how ideas evolve across iterations and influences | none |
| 144 | think-deeply | Prevents confirmatory answers by encouraging nuanced multi-perspective analysis for complex questions | none |
| 145 | obsidian-markdown | Structured markdown authoring and knowledge workflows optimized for Obsidian vaults | none |
| 146 | json-canvas | Work with Obsidian JSON Canvas for visual knowledge mapping and linking | none |
| 147 | teach | Learn a concept over multiple sessions using the current directory as a stateful workspace with glossary, missio... | none |
| 148 | teaching-skills | University teaching-lifecycle suite for professors: course design, lessons, assessment, grading, and reflection... | none |
| 149 | youtube-transcript | Summarize YouTube transcripts | none |
| 150 | claude-epub-skill | Parse and analyze EPUB eBooks | none |
| 151 | Image Enhancer | Improve resolution and clarity of screenshots | none |
| 152 | Video Downloader | Download YouTube videos for use in Claude | none |
| 153 | imagen | Generate images using Google Gemini's image generation API for UI mockups, icons, and visual assets | none |
| 154 | typefully | Official Typefully skill for creating and scheduling social media content across X, LinkedIn, Threads, Bluesky,... | none |
| 155 | video-edit | Smart router that matches video-editing intent to the right model in the RunComfy catalog — restyle, background... | none |
| 156 | hyperframes | HeyGen's agent-native HTML-to-video framework: CLI development loop with keyframes, capture, render, composition... | none |
| 157 | ruxi-skill | Turn any book into a playable visual novel where you play an overlooked side character, every branch cited back... | none |
| 158 | socialclaw | Social media scheduling and publishing for AI agents across X, LinkedIn, Instagram, Facebook Pages, TikTok, Disc... | none |
| 159 | agent-workflow-pack | Package repeatable AI coding workflows into SKILL.md, templates, and verification checks | writing-skills (partial) |
| 160 | grill-me | Structured questioning workflow to pressure-test plans and designs before execution | superpowers-extended-cc:brainstorming (partial) |
| 161 | handoff | Generate concise handoff documentation so another agent can continue work seamlessly | handoff (~/.claude/skills) |
| 162 | grilling | Grill the user relentlessly about a plan or design — one question at a time with a recommended answer | superpowers-extended-cc:brainstorming (partial) |
| 163 | loop-me | Grill about specs for the workflows you want to build, using the current directory as a stateful workspace | none |
| 164 | Meeting Insights Analyzer | Analyze meeting dynamics and communication patterns | meeting-follow-up (plugin) (partial) |
| 165 | Notion Integration Skills | Official Notion connectors for Claude | none |
| 166 | commands | Manage and automate recurring project commands | none |
| 167 | receiving-code-review | Process and apply code review feedback | superpowers-extended-cc:receiving-code-review |
| 168 | requesting-code-review | Request and manage structured code reviews | superpowers-extended-cc:requesting-code-review |
| 169 | dispatching-parallel-agents | Coordinate multiple Claude subagents on shared tasks | superpowers-extended-cc:dispatching-parallel-agents |
| 170 | remembering-conversations | Recall facts, insights, and context from past Claude Code sessions | none |
| 171 | git-pushing | Automate git operations and repository interactions | none |
| 172 | linear-claude-skill | Manage Linear issues, projects, and teams with MCP tools and GraphQL fallbacks | none |
| 173 | linear-cli-skill | A skill teaching Claude how to use linear-CLI as an alternative to Linear MCP | none |
| 174 | review-implementing | Evaluate code implementation plans and align with specs | superpowers-extended-cc:requesting-code-review (partial) |
| 175 | test-fixing | Detect failing tests and propose patches or fixes | superpowers-extended-cc:systematic-debugging (partial) |
| 176 | product-manager-skills | Senior PM agent with 6 knowledge domains, 12 templates, 30+ frameworks covering discovery, strategy, delivery, S... | project-status; weekly-plan (partial) |
| 177 | read-only-gh-pr-review | Safe read-only review of backend pull requests using GitHub CLI with local inspection | none |
| 178 | i-have-adhd | Shapes agent output for ADHD readers: lead with the next action, number multi-step work, restate state across tu... | none |
| 179 | yylo-skills | Seven reusable agent skills for Claude Code, Codex, and Pi built around YYLO Ledger — operate task management, m... | none |
| 180 | copywriting | Expert conversion copywriter skill that prioritizes clarity and business outcomes with proven frameworks | none |
| 181 | seo-audit | Technical and on-page SEO review for websites | none |
| 182 | ai-seo | AI search engine optimization for visibility in AI-powered search results | none |
| 183 | programmatic-seo | Scaled SEO page generation for large content operations | none |
| 184 | content-strategy | Content planning and topic research for marketing teams | none |
| 185 | copy-editing | Marketing copy review and refinement for quality and conversion | none |
| 186 | email-sequence | Automated email flow development for welcome, nurture, and re-engagement series | none |
| 187 | cold-email | B2B outreach email sequence creation and optimization | none |
| 188 | ad-creative | Ad headline and creative generation for paid campaigns | none |
| 189 | ab-test-setup | A/B testing and experiment planning for marketing campaigns | none |
| 190 | page-cro | Marketing page conversion rate optimization | none |
| 191 | pricing-strategy | Pricing and monetization strategy for SaaS and products | none |
| 192 | launch-strategy | Product launch planning and go-to-market strategy | none |
| 193 | social-content | Social media content creation across platforms | none |
| 194 | lead-magnets | Lead magnet creation and optimization for list building | none |
| 195 | referral-program | Referral and affiliate program design and implementation | none |
| 196 | sales-enablement | Sales collateral and pitch deck creation for B2B teams | none |
| 197 | analytics-tracking | Analytics setup and measurement implementation | none |
| 198 | marketing-psychology | Behavioral science application to marketing copy and UX | none |
| 199 | seo-audit-full | Deep technical and content SEO auditing workflow for comprehensive site/page analysis | none |
| 200 | vibe-prospecting | Live B2B company and contact data for natural-language lead-list building, prospect enrichment, executive discov... | none |
| 201 | reddit-automation | Find Reddit threads where people are genuinely asking for what you offer, then draft honest, helpful replies wit... | none |
| 202 | proficiently-claude-skills | AI-powered job search, resume tailoring, and cover letter writing | none |
| 203 | claude-code-job-tailor | Resume optimization system that analyzes job postings, ranks requirements, and generates tailored PDFs in under... | none |
| 204 | resume-tailoring-skill | AI-powered resume tailoring optimized for specific job descriptions while maintaining factual integrity | none |
| 205 | claude-resume-kit | Extract experience once, generate tailored LaTeX resumes per JD with anti-fabrication controls and multi-perspec... | none |
| 206 | Resume-Builder | AI-powered resume and cover letter generator with dual ATS + HR scoring for any profession | none |
| 207 | ResumeSkills | Resume optimization, ATS scoring, interview prep, and strategic job search skills collection | none |
| 208 | Trail of Bits Security Skills | Security skills for static analysis with CodeQL/Semgrep, variant analysis, code auditing, and fix verification | security-review; claude-security (partial) |
| 209 | webapp-testing | UI test automation using Playwright | claude-in-chrome (partial) |
| 210 | ffuf_claude_skill | Fuzz test web apps with FFUF + Claude | none |
| 211 | defense-in-depth | Implement multi-layered testing and security best practices | security-review (partial) |
| 212 | systematic-debugging | Structured debugging with hypothesis testing and validation | superpowers-extended-cc:systematic-debugging |
| 213 | testing-anti-patterns | Identify and prevent testing anti-patterns | none |
| 214 | testing-skills-with-subagents | Verify new skills using subagents and test cycles | superpowers-extended-cc:writing-skills |
| 215 | verification-before-completion | Run verification checks before closing tasks | superpowers-extended-cc:verification-before-completion |
| 216 | condition-based-waiting | Use logical conditions to control test flow timing | none |
| 217 | varlock-claude-skill | Secure environment variable management ensuring secrets never appear in sessions, terminals, logs, or git commits | none |
| 218 | security-fuzzing | Essential fuzzing payloads for SQL injection, command injection, NoSQL injection, and LDAP injection testing | none |
| 219 | security-payloads | Specialized attack payloads for XSS vectors, XXE, template injection, and file upload bypass testing | none |
| 220 | llm-testing | AI/ML security testing including bias detection, data leakage, alignment testing, and adversarial resistance | none |
| 221 | accessibility-skills | Accessibility guidance for accessible interfaces, including forms, keyboard use, color contrast, and light/dark... | accessibility-review (plugin) |
| 222 | security-hardening | Portable defensive security workflow covering secure design and review, OWASP, MCP security, prompt injection, i... | security-review (partial) |
| 223 | writing-great-skills | Reference for writing and editing skills well — the vocabulary and principles that make a skill predictable | writing-for-agents; superpowers-extended-cc:writing-skills |
| 224 | git-guardrails-claude-code | Install guardrails to block dangerous git commands before execution | update-config (partial) |
| 225 | setup-pre-commit | Configure Husky pre-commit hooks with lint-staged, formatting, and quality checks | none |
| 226 | file-organizer | Clean up file structures, rename documents | none |
| 227 | invoice-organizer | Parse and categorize invoices | none |
| 228 | raffle-winner-picker | Pick winners using secure randomness | none |
| 229 | skill-creator | Build your own skill interactively | anthropic-skills:skill-creator |
| 230 | template-skill | A starting template for new skills | anthropic-skills:skill-creator (partial) |
| 231 | gardening-skills-wiki | Maintain the skills wiki, ensuring naming consistency and metadata quality | anthropic-skills:skill-creator (partial) |
| 232 | pulling-updates-from-skills-repository | Sync and pull the latest skill updates from repositories | none |
| 233 | cc-devops-skills | 31 DevOps skills covering IaC, CI/CD, Kubernetes, observability, and scripting automation | none |
| 234 | opentelemetry-skills | Instrumentation, telemetry-quality, collector, semantic-convention, and OTTL guidance for observable applications | none |
| 235 | devops-claude-skills | DevOps workflow skills for Terraform, K8s troubleshooting, AWS cost optimization, and GitOps | none |
| 236 | aws-well-architected-review | Reusable playbooks for applying the AWS Well-Architected Framework to architecture reviews and improvement plans | none |
| 237 | firecrawl-cli | Official Firecrawl skill for scraping, crawling, searching, and mapping the web via CLI | none |
| 238 | hermes-tweet | Native Hermes Agent plugin skill for X monitoring, account research, trend checks, and approval-gated social act... | none |
| 239 | replicate | Official Replicate skill for discovering, comparing, and running AI models via API | none |
| 240 | agentsys | 36 workflow automation skills for profiling, code review, AI consultation, release management, and drift analysis | code-review (partial) |
| 241 | better-i18n | Official i18n skill for internationalization best practices, translation workflows, and localization automation | none |
| 242 | migrate-to-shoehorn | Migrate test assertions to @total-typescript/shoehorn patterns | none |
| 243 | scaffold-exercises | Scaffold structured exercise directories with sections, problems, solutions, and explainers | none |
| 244 | edit-article | Assist with article editing and refinement workflows | none |
| 245 | obsidian-vault | Work with and organize notes in an Obsidian vault | none |
| 246 | obsidian-cli | Use Obsidian CLI workflows to automate vault operations and content management | none |
| 247 | wizard | Generate an interactive bash wizard that walks a human through a manual procedure — opening URLs, capturing valu... | none |
| 248 | setup-ts-deep-modules | Wire dependency-cruiser into a TypeScript repo so each package is a deep module with a small public surface | none |
| 249 | claude-handoff | Hand the current conversation off to a fresh background agent that picks up the work immediately | handoff (~/.claude/skills) |
| 250 | find-skills | Official Vercel skill that discovers and installs agent skills from the ecosystem when you ask "is there a skill... | anthropic-skills:find-skills |
| 251 | danshari-skill (断舍离.skill) | Audits every skill you have installed and archives the ones your current model, harness, or MCP servers already... | claude-automation-recommender (partial) |
| 252 | sijiao-skill (私教.skill) | Distils any skill you want to learn into a stateful tutor — it remembers where you are, sets and grades exercise... | none |

## Shortlist

Skills that are not in this repo, only linked from it. Each was cloned shallow into its own scratchpad directory and read, never run.

### 1. terraform-skill (`antonbabenko/terraform-skill`, commit 9c1e92d, 2026-10-24)
- **Why:** Terraform/OpenTofu best practices (modules, testing, CI, scans, state operations, security). Matches the user's GCP and Terraform work.
- **Replaces or extends:** nothing installed covers Terraform, so it adds a new skill. The `gitlab-ci-loop` skill is related but only handles the CI loop.
- **Where it would live:** `~/.claude/skills/terraform-skill/` (the skill folder is `skills/terraform-skill/`: `SKILL.md` plus 8 files in `references/`). Don't install the repo root, which also has a `mcp.json`.
- **Licence:** Apache-2.0 (`LICENSE`, and `license: Apache-2.0` in the frontmatter).
- **Caveat:** I did not read its references in depth, so I can't say how well it covers GCP or GitLab CI (its `ci-cd-workflows.md` exists, contents not checked).

### 2. terraform-test and terraform-style-guide (`hashicorp/agent-skills`, `plugins/terraform/skills/`, commit f706481, 2026-09-28)
- **Why:** HashiCorp's own guidance for `terraform test` (mock providers, CI) and HCL style.
- **Replaces or extends:** overlaps `terraform-skill` in part. Take them only if the first leaves gaps.
- **Where it would live:** `~/.claude/skills/terraform-test/` and `~/.claude/skills/terraform-style-guide/`.
- **Licence:** MPL-2.0 (repo `LICENSE`). It is file-level copyleft, so keep the files unmodified or keep the notices.
- **Not shortlisted from the same repo:** the provider-development skills (not the user's work), `terraform-policy` (Sentinel/AWS examples), `terraform-stacks` (HCP-specific), `terraform-search-import` (see Security read).

### 3. gitlab-ci-validator (`akin-ozer/cc-devops-skills`, `devops-skills-plugin/skills/gitlab-ci-validator`, commit 276af75, 2026-07-11): lowest priority
- **Why:** static checks (syntax, best practices, security patterns) for `.gitlab-ci.yml`.
- **Replaces or extends:** extends `gitlab-ci-loop`, which iterates on pipelines but does not lint them statically.
- **Where it would live:** `~/.claude/skills/gitlab-ci-validator/`.
- **Licence:** Apache-2.0 (repo `LICENSE`).
- **Verdict:** only if linting is wanted. See the Security read for the install side effects.

### Considered and not shortlisted
- `coreyhaines31/marketingskills` (MIT): 22 marketing skills (`analytics-tracking`, `ab-test-setup`, ...) that would suit the agency. Its repo bundles about 100 third-party CLIs under `tools/clis/*.js`. Those are not part of the skills, but vetting them was out of scope. Revisit if the user wants marketing skills.
- `google-agents-cli-deploy` (Cloud Run/GKE deploy for ADK agents): too narrow. Not cloned.
- BigQuery and Pub/Sub: no skill in the index covers them (`clickhouse`, `tinybird` and `supabase-postgres` are other products).

## Security read

All 252 entries are links. The collection repo has no scripts, hooks or executables (`git ls-files` returns only `README.md`). The reads below cover the bundled files of the shortlisted skills only.

| Skill | Bundled executables | What they run / touch | Verdict |
|-------|---------------------|-----------------------|---------|
| terraform-skill | none under `skills/terraform-skill/` (`SKILL.md` + `references/*.md`). The repo has `.github/release/*.js` (build tooling, not part of the skill) and an `mcp.json` that runs `docker run hashicorp/terraform-mcp-server:latest`. | The skill is text only. The `mcp.json` is not part of the skill folder and would only matter if copied into an MCP config. | Safe to install as text. Do not copy `mcp.json` without a separate decision (unpinned `:latest` image). |
| terraform-test | none (`SKILL.md` + `references/*.md`) | Nothing runs. | Safe. |
| terraform-style-guide | none (`SKILL.md`, `SECURITY.md`) | Nothing runs. | Safe. |
| gitlab-ci-validator | `scripts/validate_gitlab_ci.sh`, `python_wrapper.sh`, `install_tools.sh`, `validate_syntax.py`, `check_security.py`, `check_best_practices.py` (about 4,000 lines) | The `.py` files only read the target YAML (`open(file, 'r')`; no `subprocess`, `os.system`, network or socket imports found by grep). `python_wrapper.sh` creates a persistent venv and runs `pip install pyyaml` if PyYAML is missing. `install_tools.sh` runs `npm install -g gitlab-ci-local` (or `--save-dev`) and checks Docker. `validate_gitlab_ci.sh` runs `gitlab-ci-local --list` (lists jobs, does not execute them) and uses `mktemp -d` with cleanup. | Moderate: no obvious malice from grep, but a full read of 4,000 lines was not done. The installs (pip, npm global) touch the system, so run them manually and review first. |
| terraform-search-import (hashicorp, not shortlisted) | `scripts/list_resources.sh` (38 lines) | Runs `terraform init -upgrade` and `terraform providers schema -json` in the current directory, so it downloads providers. | Not adopted. Fine in principle, but it does network I/O. |

Prompt-injection note: the README descriptions and the linked SKILL.md files are untrusted text. Nothing in them was followed as an instruction. The skills read here had no `allowed-tools` frontmatter (grep on the `gitlab-ci-validator`, `terraform-test` and `terraform-style-guide` SKILL.md files found none), so they would add no extra tool permissions.

## Method

Commands run (scratchpad `/tmp/skills-scout.js7FWO/` for the collection repo, `.../scratchpad/c/` for the candidates; nothing was executed from either):

- `git clone --depth 1 https://github.com/abubakarsiddik31/claude-skills-collection $D/repo`, then `find $D/repo -name SKILL.md | wc -l` returned 0, and `git ls-files` returned only `README.md`.
- `grep -E '^\| \*\*' README.md | wc -l` returned 252. `grep -c 'https://github.com' README.md` returned 259 (includes non-table links).
- Installed skills: listed `~/.claude/skills/*/SKILL.md` and `agent-board/claude/skills/*/SKILL.md` (context-canary, docs-*, fix-merge-conflicts, gitlab-ci-loop, handoff, requesting-code-review-extras, retro, test-driven-development-extras, tmux-orchestrator, writing-for-agents, writing-plans-extras); `find ~/.claude/plugins -name SKILL.md` for the plugin skills.
- Table built by `python3 -I gen.py` (a script in the scratchpad, outside the clone) from the 252 README rows plus a hand-written overlap map. Output: 252 rows, 175 with overlap `none`. The overlap judgements are mine, from names and one-line descriptions.
- Shallow clones of `antonbabenko/terraform-skill`, `hashicorp/agent-skills`, `akin-ozer/cc-devops-skills`, `coreyhaines31/marketingskills`, each into its own directory. Used `find` for scripts, `grep` for `curl|wget|pip|npm|sudo|eval|subprocess|http`, and `sed`/`head` on LICENSE files and scripts.
- Not done: live GitHub star/maintenance checks, full reads of the 4,000-line validator, and content checks of the other 249 entries (their skill bodies were not read).
