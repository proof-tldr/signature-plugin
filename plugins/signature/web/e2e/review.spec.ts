import { expect, test } from '@playwright/test'

test('each relationship reads from both sides, with real examples', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Each order has exactly one customer.')).toBeVisible()
  await expect(page.getByText('A customer can have any number of orders, including none.')).toBeVisible()
  await expect(page.getByText('Order 1042: customer Acme Corp')).toBeVisible()
  await expect(page.getByText('Each order line ties together an order and a product, with its quantity.')).toBeVisible()
  await expect(page.getByText('Agreed price depends on a customer, a product and a region together.')).toBeVisible()
})

test('picking a thing in the diagram opens its row', async ({ page }) => {
  await page.goto('/')
  await page.locator('.react-flow__node-thing', { hasText: 'Products' }).click()

  const row = page.getByRole('button', { name: /^Products/ })
  await expect(row).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('From your products file')).toBeVisible()
})

test('publishing asks first, says who sees it, then confirms', async ({ page }) => {
  await page.goto('/')
  const total = await page.getByRole('button', { name: 'Correct' }).count()
  for (const button of await page.getByRole('button', { name: 'Correct' }).all()) await button.click()
  await expect(page.getByText(`${total} of ${total} reviewed`)).toBeVisible()

  await page.getByRole('button', { name: 'Publish', exact: true }).click()
  const confirm = page.getByRole('dialog', { name: 'Publish Acme Supply?' })
  await expect(confirm.getByText('You can correct it and publish again at any time.', { exact: false })).toBeVisible()
  await confirm.getByRole('button', { name: 'Publish', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Acme Supply is published' })).toBeVisible()
})

test('marking something wrong asks what is wrong with it, counts as reviewed, and sends it', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Wrong' }).nth(1).click()

  await expect(page.getByText('1 of 12 reviewed')).toBeVisible()
  const panel = page.getByRole('dialog', { name: 'What is wrong?' })
  const answer = panel.getByRole('textbox', { name: 'Orders and Customers' })
  await expect(answer).toBeFocused()
  await answer.fill('a big order can be split between two customers')
  await panel.getByRole('button', { name: 'Send to Signature' }).click()
  await expect(page.getByRole('heading', { name: 'Your corrections are with Signature' })).toBeVisible()
})

test("the page speaks the customer's language, not the database's", async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /^Orders/ }).click()
  await expect(page.getByText('From the orders table in your sales database')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'Placed on' })).toBeVisible()
  for (const jargon of ['public.', 'PostgreSQL', 'order_lines', 'entity', 'field', 'string']) {
    await expect(page.getByText(jargon, { exact: false })).toHaveCount(0)
  }
})

test('the connect page names its database, and helps someone without the details', async ({ page }) => {
  await page.goto('/?page=connect')
  await page.getByRole('button', { name: "I don't have these details" }).click()
  await expect(page.getByText('Ask whoever looks after this database, often IT')).toBeVisible()
  await page.getByLabel('Database name').fill('shop')
  await page.getByLabel('User').fill('reader')
  await page.getByRole('button', { name: 'Connect' }).click()
  await expect(page.getByRole('heading', { name: 'sales is connected' })).toBeVisible()
})
