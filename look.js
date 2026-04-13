// Snake Game JavaScript
document.addEventListener('DOMContentLoaded', function() {
  // Particle system for visual effects
  class Particle {
    constructor(x, y, color) {
      this.x = x;
      this.y = y;
      this.color = color;
      this.size = Math.random() * 4 + 2;
      this.speedX = Math.random() * 3 - 1.5;
      this.speedY = Math.random() * 3 - 1.5;
      this.life = 1;
      this.decay = Math.random() * 0.02 + 0.01;
    }

    update() {
      this.x += this.speedX;
      this.y += this.speedY;
      this.life -= this.decay;
      this.size *= 0.98;
    }

    draw(ctx) {
      ctx.save();
      ctx.globalAlpha = this.life;
      ctx.fillStyle = this.color;
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }

  class ParticleSystem {
    constructor() {
      this.particles = [];
    }

    createExplosion(x, y, color, count = 15) {
      for (let i = 0; i < count; i++) {
        this.particles.push(new Particle(x, y, color));
      }
    }

    update() {
      for (let i = this.particles.length - 1; i >= 0; i--) {
        this.particles[i].update();
        if (this.particles[i].life <= 0) {
          this.particles.splice(i, 1);
        }
      }
    }

    draw(ctx) {
      this.particles.forEach(particle => particle.draw(ctx));
    }
  }

  // Game variables
  const canvas = document.getElementById('game-canvas');
  const ctx = canvas.getContext('2d');
  const particleSystem = new ParticleSystem();
  const scoreElement = document.getElementById('score');
  const highScoreElement = document.getElementById('high-score');
  const speedElement = document.getElementById('speed');
  const startBtn = document.getElementById('start-btn');
  const pauseBtn = document.getElementById('pause-btn');
  const resetBtn = document.getElementById('reset-btn');
  const restartBtn = document.getElementById('restart-btn');
  const gameOverElement = document.getElementById('game-over');
  const finalScoreElement = document.getElementById('final-score');

  // Helper function for rounded rectangles
  function roundRect(ctx, x, y, width, height, radius) {
    if (width < 2 * radius) radius = width / 2;
    if (height < 2 * radius) radius = height / 2;
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + width, y, x + width, y + height, radius);
    ctx.arcTo(x + width, y + height, x, y + height, radius);
    ctx.arcTo(x, y + height, x, y, radius);
    ctx.arcTo(x, y, x + width, y, radius);
    ctx.closePath();
  }

  // Game constants
  const GRID_SIZE = 20;
  const GRID_WIDTH = canvas.width / GRID_SIZE;
  const GRID_HEIGHT = canvas.height / GRID_SIZE;

  // Game state
  let snake = [];
  let food = {};
  let direction = 'right';
  let nextDirection = 'right';
  let gameSpeed = 150;
  // ms
  let score = 0;
  let highScore = localStorage.getItem('snakeHighScore') || 0;
  let gameRunning = false;
  let gameLoop;

  // Initialize game
  function init() {
    // Set high score
    highScoreElement.textContent = highScore;

    // Create initial snake
    snake = [{
      x: 5,
      y: 10
    }, {
      x: 4,
      y: 10
    }, {
      x: 3,
      y: 10
    }];

    // Generate first food
    generateFood();

    // Draw initial state
    draw();

    // Hide game over screen
    gameOverElement.style.display = 'none';
  }

  // Generate food at random position
  function generateFood() {
    food = {
      x: Math.floor(Math.random() * GRID_WIDTH),
      y: Math.floor(Math.random() * GRID_HEIGHT)
    };

    // Make sure food doesn't appear on snake
    for (let segment of snake) {
      if (segment.x === food.x && segment.y === food.y) {
        generateFood();
        return;
      }
    }
  }

  // Draw game elements
  function draw() {
    // Draw gradient background
    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, '#0a192f');
    gradient.addColorStop(0.5, '#1a1a2e');
    gradient.addColorStop(1, '#16213e');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Draw grid with subtle glow effect
    ctx.strokeStyle = 'rgba(100, 150, 255, 0.1)';
    ctx.lineWidth = 0.8;
    ctx.shadowBlur = 2;
    ctx.shadowColor = 'rgba(100, 150, 255, 0.3)';
    for (let x = 0; x < canvas.width; x += GRID_SIZE) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
    }
    for (let y = 0; y < canvas.height; y += GRID_SIZE) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(canvas.width, y);
      ctx.stroke();
    }

    // Draw snake
    snake.forEach((segment, index) => {
      if (index === 0) {
        // Snake head with gradient and rounded corners
        const headX = segment.x * GRID_SIZE;
        const headY = segment.y * GRID_SIZE;

        // Create gradient for head
        const headGradient = ctx.createLinearGradient(
          headX, headY,
          headX + GRID_SIZE, headY + GRID_SIZE
        );
        headGradient.addColorStop(0, '#00ff9d');
        headGradient.addColorStop(1, '#00b894');

        // Draw rounded head
        ctx.fillStyle = headGradient;
        roundRect(ctx, headX, headY, GRID_SIZE, GRID_SIZE, 5);
        ctx.fill();

        // Draw eyes with glow
        ctx.fillStyle = '#000';
        ctx.shadowBlur = 3;
        ctx.shadowColor = '#00ff9d';
        const eyeSize = GRID_SIZE / 5;
        const offset = GRID_SIZE / 3;

        if (direction === 'right') {
          ctx.fillRect(segment.x * GRID_SIZE + GRID_SIZE - offset, segment.y * GRID_SIZE + offset, eyeSize, eyeSize);
          ctx.fillRect(segment.x * GRID_SIZE + GRID_SIZE - offset, segment.y * GRID_SIZE + GRID_SIZE - offset - eyeSize, eyeSize, eyeSize);
        } else if (direction === 'left') {
          ctx.fillRect(segment.x * GRID_SIZE + offset - eyeSize, segment.y * GRID_SIZE + offset, eyeSize, eyeSize);
          ctx.fillRect(segment.x * GRID_SIZE + offset - eyeSize, segment.y * GRID_SIZE + GRID_SIZE - offset - eyeSize, eyeSize, eyeSize);
        } else if (direction === 'up') {
          ctx.fillRect(segment.x * GRID_SIZE + offset, segment.y * GRID_SIZE + offset - eyeSize, eyeSize, eyeSize);
          ctx.fillRect(segment.x * GRID_SIZE + GRID_SIZE - offset - eyeSize, segment.y * GRID_SIZE + offset - eyeSize, eyeSize, eyeSize);
        } else if (direction === 'down') {
          ctx.fillRect(segment.x * GRID_SIZE + offset, segment.y * GRID_SIZE + GRID_SIZE - offset, eyeSize, eyeSize);
          ctx.fillRect(segment.x * GRID_SIZE + GRID_SIZE - offset - eyeSize, segment.y * GRID_SIZE + GRID_SIZE - offset, eyeSize, eyeSize);
        }
      } else {
        // Snake body with gradient and rounded corners
        const bodyX = segment.x * GRID_SIZE;
        const bodyY = segment.y * GRID_SIZE;

        // Create gradient for body (darker as we go further from head)
        const bodyGradient = ctx.createLinearGradient(
          bodyX, bodyY,
          bodyX + GRID_SIZE, bodyY + GRID_SIZE
        );
        const intensity = 1 - (index / snake.length) * 0.3;
        bodyGradient.addColorStop(0, `rgba(78, 204, 163, ${intensity})`);
        bodyGradient.addColorStop(1, `rgba(61, 170, 138, ${intensity})`);

        // Draw rounded body segment
        ctx.fillStyle = bodyGradient;
        ctx.shadowBlur = 0;
        roundRect(ctx, bodyX, bodyY, GRID_SIZE, GRID_SIZE, 3);
        ctx.fill();

        // Inner highlight for 3D effect
        ctx.fillStyle = `rgba(255, 255, 255, 0.1)`;
        roundRect(ctx, bodyX + 2, bodyY + 2, GRID_SIZE - 4, GRID_SIZE - 4, 2);
        ctx.fill();
      }
    });

    // Draw food with gradient and glow
    const foodX = food.x * GRID_SIZE + GRID_SIZE / 2;
    const foodY = food.y * GRID_SIZE + GRID_SIZE / 2;
    const foodRadius = GRID_SIZE / 2 - 2;

    // Create radial gradient for food
    const foodGradient = ctx.createRadialGradient(
      foodX, foodY, 0,
      foodX, foodY, foodRadius
    );
    foodGradient.addColorStop(0, '#ff9e00');
    foodGradient.addColorStop(0.7, '#ff6b6b');
    foodGradient.addColorStop(1, '#ff4757');

    // Draw food with glow effect
    ctx.shadowBlur = 10;
    ctx.shadowColor = '#ff6b6b';
    ctx.fillStyle = foodGradient;
    ctx.beginPath();
    ctx.arc(foodX, foodY, foodRadius, 0, Math.PI * 2);
    ctx.fill();

    // Draw food shine with animation
    const time = Date.now() * 0.001;
    const shineOffset = Math.sin(time * 5) * 2;
    ctx.shadowBlur = 5;
    ctx.shadowColor = '#ffffff';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.beginPath();
    ctx.arc(
      foodX - 3 + shineOffset,
      foodY - 3 + shineOffset,
      GRID_SIZE / 6,
      0,
      Math.PI * 2
    );
    ctx.fill();

    // Draw pulsing effect
    ctx.shadowBlur = 0;
    ctx.strokeStyle = 'rgba(255, 107, 107, 0.3)';
    ctx.lineWidth = 1;
    const pulseSize = Math.sin(time * 3) * 2 + foodRadius + 4;
    ctx.beginPath();
    ctx.arc(foodX, foodY, pulseSize, 0, Math.PI * 2);
    ctx.stroke();

    // Update and draw particles
    particleSystem.update();
    particleSystem.draw(ctx);
  }

  // Update game state
  function update() {
    // Update direction
    direction = nextDirection;

    // Calculate new head position
    const head = {
      ...snake[0]
    };

    switch (direction) {
      case 'up':
        head.y -= 1;
        break;
      case 'down':
        head.y += 1;
        break;
      case 'left':
        head.x -= 1;
        break;
      case 'right':
        head.x += 1;
        break;
    }

    // Check wall collision
    if (head.x < 0 || head.x >= GRID_WIDTH || head.y < 0 || head.y >= GRID_HEIGHT) {
      gameOver();
      return;
    }

    // Check self collision
    for (let segment of snake) {
      if (head.x === segment.x && head.y === segment.y) {
        gameOver();
        return;
      }
    }

    // Add new head
    snake.unshift(head);

    // Check food collision
    if (head.x === food.x && head.y === food.y) {
      // Increase score
      score += 10;
      scoreElement.textContent = score;

      // Create particle explosion at food position
      const foodX = food.x * GRID_SIZE + GRID_SIZE / 2;
      const foodY = food.y * GRID_SIZE + GRID_SIZE / 2;
      particleSystem.createExplosion(foodX, foodY, 20, '#ff9e00', '#ff6b6b', '#ff4757');

      // Generate new food
      generateFood();

      // Increase speed every 50 points
      if (score % 50 === 0 && gameSpeed > 50) {
        gameSpeed -= 20;
        clearInterval(gameLoop);
        gameLoop = setInterval(gameStep, gameSpeed);
        updateSpeedDisplay();
      }
    } else {
      // Remove tail if no food eaten
      snake.pop();
    }

    // Draw updated game
    draw();
  }

  // Game step function
  function gameStep() {
    if (gameRunning) {
      update();
    }
  }

  // Start game
  function startGame() {
    if (!gameRunning) {
      gameRunning = true;
      gameLoop = setInterval(gameStep, gameSpeed);
      startBtn.innerHTML = '<i class="fas fa-play"></i> Resume';
      pauseBtn.disabled = false;
    }
  }

  // Pause game
  function pauseGame() {
    gameRunning = !gameRunning;
    if (gameRunning) {
      pauseBtn.innerHTML = '<i class="fas fa-pause"></i> Pause';
    } else {
      pauseBtn.innerHTML = '<i class="fas fa-play"></i> Resume';
    }
  }

  // Reset game
  function resetGame() {
    clearInterval(gameLoop);
    gameRunning = false;
    score = 0;
    gameSpeed = 150;
    direction = 'right';
    nextDirection = 'right';
    scoreElement.textContent = score;
    speedElement.textContent = 'Normal';
    init();
    startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
    pauseBtn.disabled = true;
    pauseBtn.innerHTML = '<i class="fas fa-pause"></i> Pause';
    gameOverElement.style.display = 'none';
  }

  // Update speed display
  function updateSpeedDisplay() {
    if (gameSpeed >= 130) {
      speedElement.textContent = 'Slow';
    } else if (gameSpeed >= 90) {
      speedElement.textContent = 'Normal';
    } else if (gameSpeed >= 50) {
      speedElement.textContent = 'Fast';
    } else {
      speedElement.textContent = 'Extreme';
    }
  }

  // Game over function
  function gameOver() {
    gameRunning = false;
    clearInterval(gameLoop);

    // Create explosion at snake head position
    if (snake.length > 0) {
      const head = snake[0];
      const headX = head.x * GRID_SIZE + GRID_SIZE / 2;
      const headY = head.y * GRID_SIZE + GRID_SIZE / 2;
      particleSystem.createExplosion(headX, headY, 30, '#ff4757', '#ff3838', '#ff0000');
    }

    // Update high score
    if (score > highScore) {
      highScore = score;
      localStorage.setItem('snakeHighScore', highScore);
      highScoreElement.textContent = highScore;
    }

    // Show game over screen
    finalScoreElement.textContent = score;
    gameOverElement.style.display = 'flex';
  }

  // Keyboard controls
  document.addEventListener('keydown', function(event) {
    switch (event.key) {
      case 'ArrowUp':
        if (direction !== 'down') nextDirection = 'up';
        break;
      case 'ArrowDown':
        if (direction !== 'up') nextDirection = 'down';
        break;
      case 'ArrowLeft':
        if (direction !== 'right') nextDirection = 'left';
        break;
      case 'ArrowRight':
        if (direction !== 'left') nextDirection = 'right';
        break;
      case ' ':
        if (gameRunning) {
          pauseGame();
        } else {
          startGame();
        }
        break;
    }
  });

  // Button event listeners
  startBtn.addEventListener('click', startGame);
  pauseBtn.addEventListener('click', pauseGame);
  resetBtn.addEventListener('click', resetGame);
  restartBtn.addEventListener('click', function() {
    resetGame();
    startGame();
  });

  // Initialize the game
  init();
  updateSpeedDisplay();
});