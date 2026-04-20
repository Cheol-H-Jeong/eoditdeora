<script lang="ts">
  let { children } = $props();
</script>

<main class="shell">
  {@render children()}
</main>

<style>
  :global(body) {
    margin: 0;
    background: #0b0d11;
    color: #e8e8ea;
    font-family: "Pretendard", "Apple SD Gothic Neo", -apple-system, BlinkMacSystemFont,
      "Noto Sans CJK KR", sans-serif;
  }
  :global(*) {
    box-sizing: border-box;
  }
  .shell {
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }
</style>
