import { expect, test } from "@playwright/test"
import { findLastEmail } from "./utils/mailcatcher"
import { createUser } from "./utils/privateApi"
import { randomEmail } from "./utils/random"
import { logInUser } from "./utils/userUtils"

test.use({ storageState: { cookies: [], origins: [] } })

test.describe("Route Metadata", () => {
  test("Recover password route title", async ({ page }) => {
    await page.goto("/recover-password")
    await expect(page).toHaveTitle("Recover Password - FastAPI Cloud")
  })

  test("Reset password route title", async ({ page }) => {
    await page.goto("/reset-password")
    await expect(page).toHaveTitle("Reset Password - FastAPI Cloud")
  })
})

test("Recover Password title is visible", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByText("Recover Password")).toBeVisible()
})

test("Input is visible, empty and editable", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByTestId("email-input")).toBeVisible()
  await expect(page.getByTestId("email-input")).toHaveText("")
  await expect(page.getByTestId("email-input")).toBeEditable()
})

test("Continue button is visible", async ({ page }) => {
  await page.goto("/recover-password")

  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible()
})

test("User can reset password successfully using the link", async ({
  page,
  request,
}) => {
  const email = randomEmail()
  const password = "changethis"
  const newPassword = "changethat"

  await createUser({ email, password })

  await page.goto("/recover-password")
  await page.getByTestId("email-input").fill(email)

  await page.getByRole("button", { name: "Continue" }).click()

  const emailData = await findLastEmail({
    request,
    filter: (e) =>
      e.recipients.includes(`<${email}>`) &&
      e.subject.toLowerCase().includes("password recovery"),
    timeout: 5000,
  })

  await page.goto(
    `${process.env.MAILCATCHER_HOST}/messages/${emailData.id}.html`,
  )

  const selector = 'a[href*="/reset-password?token="]'

  let url = await page.getAttribute(selector, "href")

  // TODO: update var instead of doing a replace
  url = url!.replace("http://localhost/", "http://localhost:5173/")

  // Set the new password and confirm it
  await page.goto(url)

  await page.getByTestId("password-input").fill(newPassword)
  await page.getByTestId("confirm-password-input").fill(newPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()
  await expect(page.getByText("Password updated successfully")).toBeVisible()

  // Check if the user is able to login with the new password
  await logInUser(page, email, newPassword)
})

test("Expired or invalid reset link", async ({ page }) => {
  const invalidUrl = "/reset-password?token=invalidtoken"
  const newPassword = "newpassword"

  await page.goto(invalidUrl)

  await page.getByTestId("password-input").fill(newPassword)
  await page.getByTestId("confirm-password-input").fill(newPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()

  await expect(page.getByText("Invalid credentials")).toBeVisible()
})

test("Weak new password validation", async ({ page, request }) => {
  const email = randomEmail()
  const password = "password"
  const weakPassword = "123"

  await createUser({ email, password })

  await page.goto("/recover-password")
  await page.getByTestId("email-input").fill(email)
  await page.getByRole("button", { name: "Continue" }).click()

  const emailData = await findLastEmail({
    request,
    filter: (e) =>
      e.recipients.includes(`<${email}>`) &&
      e.subject.toLowerCase().includes("password recovery"),
    timeout: 5000,
  })

  await page.goto(
    `${process.env.MAILCATCHER_HOST}/messages/${emailData.id}.html`,
  )

  const selector = 'a[href*="/reset-password?token="]'
  let url = await page.getAttribute(selector, "href")
  url = url!.replace("http://localhost/", "http://localhost:5173/")

  // Set a weak new password
  await page.goto(url)
  await page.getByTestId("confirm-password-input").fill(weakPassword)
  await page.getByTestId("password-input").fill(weakPassword)
  await page.getByRole("button", { name: "Reset Password" }).click()

  await expect(
    page.getByText("Password must be at least 8 characters"),
  ).toBeVisible()
})
