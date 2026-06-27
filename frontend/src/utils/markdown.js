/**
 * Markdown 渲染工具
 *
 * 基于 markdown-it + highlight.js 实现：
 * - 代码块语法高亮（highlight.js，github-dark 主题）
 * - XSS 防护（禁用 raw HTML）
 * - 一键复制支持（通过 wrapCodeBlocks 辅助函数）
 * - [来源N] 引用锚点解析（ResearchMind 新增，对齐 FRONTEND.md §4.5.3）
 *
 * 来源：DocMind `frontend/src/utils/markdown.js`，ResearchMind 扩展引用锚点 plugin。
 */

import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

// 创建 markdown-it 实例
const md = new MarkdownIt({
  html: false,        // 禁用 raw HTML，防止 XSS
  linkify: true,      // 自动识别链接
  typographer: false,
  breaks: true,       // 换行符转 <br>
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        const result = hljs.highlight(str, { language: lang, ignoreIllegals: true })
        return result.value
      } catch {
        // 高亮失败时降级
      }
    }
    // 无语言指定或高亮失败时，使用 escapeHtml
    return md.utils.escapeHtml(str)
  },
})

/**
 * [来源N] 引用锚点解析 plugin
 *
 * 对齐 RESEARCH_PIPELINE.md §8.4 + FRONTEND.md §4.5.3：
 * - 匹配正文中所有 [来源N] 标记
 * - 渲染为 <a class="citation-link" data-evidence-index="N">[来源N]</a>
 * - 点击事件由组件层通过事件委托处理（联动 Evidence Graph 面板）
 */
md.use((mdInstance) => {
  const defaultRender = mdInstance.renderer.rules.text || function (tokens, idx) {
    return mdInstance.utils.escapeHtml(tokens[idx].content)
  }

  mdInstance.renderer.rules.text = function (tokens, idx) {
    const content = tokens[idx].content
    // 匹配 [来源N]、[来源N,M]、[来源N-M]
    const citationRegex = /\[来源(\d+(?:[,，\-]\d+)*)\]/g

    if (!citationRegex.test(content)) {
      return defaultRender(tokens, idx)
    }

    // 重置 lastIndex
    citationRegex.lastIndex = 0
    let lastIndex = 0
    let result = ''

    let match
    while ((match = citationRegex.exec(content)) !== null) {
      // 添加匹配前的文本
      result += mdInstance.utils.escapeHtml(content.slice(lastIndex, match.index))
      // 渲染引用锚点（空格分隔，支持 [data-evidence-index~="N"] 精确选择）
      const rawIndices = match[1].split(/[,，\-]/)
      const indices = rawIndices.join(' ')
      // 内部仍按 0-based 索引联动 Evidence 面板，但前端展示从 1 开始
      const displayIndices = rawIndices.map(i => Number(i) + 1).join(',')
      result += `<a class="citation-link" data-evidence-index="${indices}">[来源${displayIndices}]</a>`
      lastIndex = citationRegex.lastIndex
    }
    // 添加剩余文本
    result += mdInstance.utils.escapeHtml(content.slice(lastIndex))
    return result
  }
})

/**
 * 渲染 Markdown 文本为 HTML
 * @param {string} text - Markdown 文本
 * @returns {string} 渲染后的 HTML
 */
export function renderMarkdown(text) {
  if (!text) return ''
  return md.render(text)
}

/**
 * 生成带复制按钮的代码块包装 HTML
 * 对齐 FRONTEND.md §4.5.3：代码块一键复制
 *
 * @param {string} html - 渲染后的 HTML
 * @returns {string} 包装后的 HTML
 */
export function wrapCodeBlocks(html) {
  return html.replace(
    /<pre><code(.*?)>([\s\S]*?)<\/code><\/pre>/g,
    (match, attrs, code) => {
      return `<div class="code-block-wrapper">
        <button class="code-copy-btn" title="复制代码" onclick="navigator.clipboard.writeText(this.dataset.code); this.classList.add('copied'); setTimeout(() => this.classList.remove('copied'), 1500)" data-code="${encodeURIComponent(code)}">
          <i class="fas fa-copy"></i>
          <i class="fas fa-check"></i>
        </button>
        <pre><code${attrs}>${code}</code></pre>
      </div>`
    }
  )
}

export default md
