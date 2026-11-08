import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  it('show=false 时不渲染任何内容', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: false, title: '标题', message: '内容' },
    })

    expect(wrapper.find('.dialog-overlay').exists()).toBe(false)
  })

  it('show=true 时渲染标题与消息', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: '确认删除', message: '该操作不可撤销' },
    })

    expect(wrapper.find('h3').text()).toBe('确认删除')
    expect(wrapper.find('.confirm-message').text()).toBe('该操作不可撤销')
  })

  it('点击取消按钮触发 cancel 事件', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 't', message: 'm', cancelText: '取消' },
    })

    await wrapper.findAll('button').find(b => b.text() === '取消')!.trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('点击确定按钮触发 confirm 事件', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 't', message: 'm', confirmText: '删除' },
    })

    await wrapper.findAll('button').find(b => b.text() === '删除')!.trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('danger 默认启用，确定按钮为危险样式', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 't', message: 'm' },
    })

    const confirmBtn = wrapper.findAll('button')[1]
    expect(confirmBtn.classes()).toContain('btn-danger')
  })

  it('danger=false 时确定按钮为主操作样式', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 't', message: 'm', danger: false },
    })

    const confirmBtn = wrapper.findAll('button')[1]
    expect(confirmBtn.classes()).toContain('btn-primary')
    expect(confirmBtn.classes()).not.toContain('btn-danger')
  })

  it('点击遮罩触发 cancel 事件', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { show: true, title: 't', message: 'm' },
    })

    await wrapper.find('.dialog-overlay').trigger('click.self')

    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })
})
