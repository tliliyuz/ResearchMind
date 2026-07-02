<template>
  <nav class="section-nav">
    <div class="section-nav-title">章节导航</div>
    <div class="section-nav-items">
      <button
        v-for="section in sections"
        :key="section.id"
        class="section-nav-item"
        :class="{ active: activeId === section.id }"
        @click="$emit('select', section.id)"
      >
        <span class="section-title" :title="section.heading">{{ section.heading }}</span>
        <span v-if="citationCount(section.id)" class="section-citation-count">
          {{ citationCount(section.id) }}
        </span>
      </button>
    </div>
    <div v-if="$slots.bottom" class="section-nav-bottom">
      <slot name="bottom" />
    </div>
  </nav>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  sections: { type: Array, default: () => [] },
  activeId: { type: String, default: null },
  evidence: { type: Array, default: () => [] },
})

defineEmits(['select'])

const countsBySection = computed(() => {
  const map = {}
  for (const section of props.sections) {
    map[section.id] = 0
  }
  for (const item of props.evidence) {
    for (const sectionId of item.usedInSections || []) {
      if (map[sectionId] != null) {
        map[sectionId]++
      }
    }
  }
  return map
})

function citationCount(sectionId) {
  return countsBySection.value[sectionId] || 0
}
</script>

<style scoped>
.section-nav {
  width: var(--rm-section-nav-width);
  background: var(--rm-bg-card);
  border-right: 1px solid var(--rm-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
  padding: var(--rm-space-2) var(--rm-space-1_5);
}

.section-nav-title {
  flex-shrink: 0;
  font-size: var(--rm-text-xs);
  font-weight: var(--rm-weight-bold);
  color: var(--rm-text-primary);
  margin-bottom: var(--rm-space-2);
  padding-left: var(--rm-space-1_5);
}

.section-nav-items {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.section-nav-bottom {
  flex-shrink: 0;
  padding-top: var(--rm-space-2);
  margin: 0 calc(-1 * var(--rm-space-1_5));
  padding-left: var(--rm-space-1_5);
  padding-right: var(--rm-space-1_5);
  border-top: 1px solid var(--rm-border);
}

.section-nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  text-align: left;
  padding: var(--rm-space-1_5) var(--rm-space-1_5);
  border-radius: var(--rm-radius-sm);
  border-left: 2px solid transparent;
  font-size: var(--rm-text-sm);
  color: var(--rm-text-secondary);
  cursor: pointer;
  transition: all var(--rm-transition-fast);
  background: transparent;
  border: none;
  border-left: 2px solid transparent;
  font-family: inherit;
  margin-bottom: var(--rm-space-0_5);
}

.section-nav-item:hover {
  background: var(--rm-bg-elevated);
}

.section-nav-item.active {
  background: var(--rm-primary-light);
  color: var(--rm-primary);
  font-weight: var(--rm-weight-semibold);
  border-left-color: var(--rm-primary);
}

.section-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.section-citation-count {
  background: var(--rm-bg-elevated);
  color: var(--rm-text-tertiary);
  font-size: var(--rm-text-xs);
  padding: var(--rm-space-0_5) var(--rm-space-1_5);
  border-radius: var(--rm-radius-pill);
  flex-shrink: 0;
  margin-left: var(--rm-space-2);
}

.section-nav-item.active .section-citation-count {
  background: var(--rm-primary-border);
  color: var(--rm-primary);
}
</style>
