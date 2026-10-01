import { expect, test } from '@playwright/test'

test('picking a concept on the map highlights it and brings its definition into view', async ({ page }) => {
  await page.goto('/')
  await page.locator('.react-flow__node-concept', { hasText: 'Products' }).click()

  const heading = page.getByRole('heading', { name: 'Products', exact: true })
  await expect(heading).toBeInViewport()
  await expect(heading.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
})

test('flagging a concept starts a change note naming it', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'This is wrong' }).first().click()

  const note = page.getByRole('textbox')
  await expect(note).toHaveValue('Customers: ')
  await expect(note).toBeFocused()
  await note.pressSequentially('test accounts are customers too')
  await page.getByRole('button', { name: 'Send changes' }).click()
  await expect(page.getByRole('heading', { name: 'Your changes are with Signature' })).toBeVisible()
})

test('publishing confirms the domain is published', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Publish' }).click()
  await expect(page.getByRole('heading', { name: 'Acme Supply is published' })).toBeVisible()
})

test('the connect page names its database and confirms the connection', async ({ page }) => {
  await page.goto('/?page=connect')
  await page.getByLabel('Database name').fill('shop')
  await page.getByLabel('User').fill('reader')
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('heading', { name: 'sales is connected' })).toBeVisible()
})
