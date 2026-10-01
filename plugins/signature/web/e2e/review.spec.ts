import { expect, test } from '@playwright/test'

test('picking a thing in the diagram brings its description into view', async ({ page }) => {
  await page.goto('/')
  await page.locator('.react-flow__node-thing', { hasText: 'Products' }).click()

  await expect(page.getByRole('heading', { name: 'Products', exact: true })).toBeInViewport()
})

test('marking everything right counts it and lets the customer publish', async ({ page }) => {
  await page.goto('/')
  const total = await page.getByRole('button', { name: 'Looks right' }).count()
  for (const button of await page.getByRole('button', { name: 'Looks right' }).all()) await button.click()

  await expect(page.getByText(`${total} of ${total}`)).toBeVisible()
  await page.getByRole('button', { name: 'Publish', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Acme Supply is published' })).toBeVisible()
})

test('marking something not quite starts a note naming it and sends it to Signature', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Not quite' }).nth(1).click()

  const note = page.getByRole('textbox')
  await expect(note).toHaveValue('Customers: ')
  await expect(note).toBeFocused()
  await note.pressSequentially('test accounts are customers too')
  await page.getByRole('button', { name: 'Send to Signature' }).click()
  await expect(page.getByRole('heading', { name: 'Signature is fixing what you flagged' })).toBeVisible()
})

test('the page speaks the customer\'s language, not the database\'s', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Each order has one customer.')).toBeVisible()
  await expect(page.getByText('Comes from the orders table in your sales database.')).toBeVisible()
  for (const jargon of ['public.', 'PostgreSQL', 'order_lines', 'entity', 'field']) {
    await expect(page.getByText(jargon, { exact: false })).toHaveCount(0)
  }
})

test('the connect page names its database and confirms the connection', async ({ page }) => {
  await page.goto('/?page=connect')
  await page.getByLabel('Database name').fill('shop')
  await page.getByLabel('User').fill('reader')
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('heading', { name: 'sales is connected' })).toBeVisible()
})
