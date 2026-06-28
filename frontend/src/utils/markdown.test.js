import { describe, it, expect } from 'vitest'
import { renderMarkdown, wrapCodeBlocks } from './markdown'

describe('wrapCodeBlocks', () => {
  it('不应包含内联 onclick 处理器', () => {
    const html = renderMarkdown('```js\nconst x = 1\n```')
    const wrapped = wrapCodeBlocks(html)

    expect(wrapped).toContain('code-block-wrapper')
    expect(wrapped).toContain('code-copy-btn')
    expect(wrapped).not.toContain('onclick=')
  })

  it('应使用隐藏 textarea 保存原始代码', () => {
    const code = 'const x = a > b ? 1 : 0'
    const html = renderMarkdown(`\`\`\`js\n${code}\n\`\`\``)
    const wrapped = wrapCodeBlocks(html)

    expect(wrapped).toContain('<textarea class="code-raw"')

    // 使用 DOMParser 提取 textarea 的原始内容（HTML 转义已还原）
    const parser = new DOMParser()
    const doc = parser.parseFromString(wrapped, 'text/html')
    const textarea = doc.querySelector('textarea.code-raw')
    expect(textarea).not.toBeNull()
    expect(textarea.value).toContain(code)
  })

  it('不应 URL 编码代码内容', () => {
    const code = 'const x = a > b ? 1 : 0'
    const html = renderMarkdown(`\`\`\`js\n${code}\n\`\`\``)
    const wrapped = wrapCodeBlocks(html)

    const parser = new DOMParser()
    const doc = parser.parseFromString(wrapped, 'text/html')
    const textarea = doc.querySelector('textarea.code-raw')
    expect(textarea.value).toContain(code)
    expect(wrapped).not.toContain(encodeURIComponent(code))
  })

  it('markdown-it 仍禁用 raw HTML', () => {
    const html = renderMarkdown('<script>alert(1)</script>')

    expect(html).not.toContain('<script>')
  })
})
